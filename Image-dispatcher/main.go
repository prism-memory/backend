//Lambda to check image format before analyze image.

package main

import (
	"context"
	"fmt"
	"io"
	"log"
	"net/url"
	"strings"
	"time"

	"github.com/aws/aws-lambda-go/lambda"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/cshum/vipsgen/vips"
)

type S3Event struct {
	S3Bucket string `json:"s3Bucket"`
	S3Key    string `json:"s3Key"`
}

type RoutingDecision struct {
	S3Bucket     string            `json:"s3Bucket"`
	S3Key        string            `json:"s3Key"`
	ImageFormat  string            `json:"imageFormat"`
	Width        int               `json:"width"`
	Height       int               `json:"height"`
	FileSize     int64             `json:"fileSize"`
	Decision     string            `json:"decision"`
	LastModified time.Time         `json:"lastModified"`
	ContentType  string            `json:"contentType"`
	UserMetadata map[string]string `json:"userMetadata"`
}

var s3Client *s3.Client

func init() {
	cfg, err := config.LoadDefaultConfig(context.TODO())
	if err != nil {
		log.Fatalf("unable to load SDK config, %v", err)
	}
	s3Client = s3.NewFromConfig(cfg)

	vips.Startup(nil)
}

func HandleRequest(ctx context.Context, event S3Event) (RoutingDecision, error) {
	defer vips.Shutdown()

	srcKey, err := url.QueryUnescape(event.S3Key)
	if err != nil {
		return RoutingDecision{}, fmt.Errorf("failed to decode S3 key: %w", err)
	}
	log.Printf("Processing image: bucket=%s, key=%s", event.S3Bucket, srcKey)

	s3Object, err := s3Client.GetObject(ctx, &s3.GetObjectInput{
		Bucket: &event.S3Bucket,
		Key:    &srcKey,
	})

	if err != nil {
		return RoutingDecision{}, fmt.Errorf("failed to get object from S3: %w", err)
	}

	lastModified := *s3Object.LastModified
	contentType := *s3Object.ContentType
	userMetadata := s3Object.Metadata

	defer func(Body io.ReadCloser) {
		err := Body.Close()
		if err != nil {

		}
	}(s3Object.Body)

	imageBytes, err := io.ReadAll(s3Object.Body)
	if err != nil {
		return RoutingDecision{}, fmt.Errorf("failed to read image body: %w", err)
	}

	image, err := vips.NewImageFromBuffer(imageBytes, nil)
	if err != nil {
		return RoutingDecision{}, fmt.Errorf("failed to process image with vips: %w", err)
	}
	defer image.Close()

	width := image.Width()
	height := image.Height()
	format, err := image.GetString("vips-loader")
	if err != nil {
		return RoutingDecision{}, fmt.Errorf("failed to get image format metadata: %w", err)
	}

	fileSizePtr := s3Object.ContentLength
	if fileSizePtr == nil {
		return RoutingDecision{}, fmt.Errorf("failed to get file size from S3 object")
	}
	fileSize := *fileSizePtr

	// For debugging
	//log.Printf("Metadata: format=%s, size=%dx%d, fileSize=%d bytes", format, width, height, fileSize)

	var decision string

	isTooLarge := width > 8000 || height > 8000 //Not Recommended on AWS Nova model
	isFormatOK := strings.Contains(format, "jpeg") || strings.Contains(format, "png") || strings.Contains(format, "webp")
	isTooSmall := width < 256 && height < 256 //Not Recommended on AWS Nova model

	if !isFormatOK || isTooLarge || isTooSmall {
		decision = "NeedsResizing"
	} else {
		decision = "IsAppropriate"
	}

	// For debugging
	/*log.Printf("Image analysis for Nova complete. Decision: %s (FormatOK: %t, TooLarge: %t, TooSmall: %t)",
	decision, isFormatOK, isTooLarge, isTooSmall)*/

	result := RoutingDecision{
		S3Bucket:     event.S3Bucket,
		S3Key:        srcKey,
		ImageFormat:  format,
		Width:        width,
		Height:       height,
		FileSize:     fileSize,
		Decision:     decision, //this is for step function choice state
		LastModified: lastModified,
		ContentType:  contentType,
		UserMetadata: userMetadata,
	}

	return result, nil
}

func main() {
	lambda.Start(HandleRequest)
}
