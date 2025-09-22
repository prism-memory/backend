//Lambda to resize image to appropriate size before analyze image.

package main

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"log"
	"path/filepath"
	"time"

	"github.com/aws/aws-lambda-go/lambda"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/cshum/vipsgen/vips"
)

type ResizeEvent struct {
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

type ResizeResult struct {
	Status       string            `json:"status"`
	S3Bucket     string            `json:"s3Bucket"`
	OriginalKey  string            `json:"originalKey"`
	S3Key        string            `json:"newKey,omitempty"`
	Message      string            `json:"message,omitempty"`
	ImageFormat  string            `json:"imageFormat"`
	Width        int               `json:"width"`
	Height       int               `json:"height"`
	FileSize     int64             `json:"fileSize"`
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
	log.Println("S3 client and vips initialized for Resizer")
}

func HandleRequest(ctx context.Context, event ResizeEvent) (ResizeResult, error) {
	if event.Width < 256 && event.Height < 256 {
		msg := fmt.Sprintf("Image is too small (%dx%d) to process.", event.Width, event.Height)
		log.Println(msg)
		return ResizeResult{
			Status:      "REJECTED_TOO_SMALL",
			OriginalKey: event.S3Key,
			Message:     msg,
		}, nil
	}

	// For debugging
	//log.Printf("Processing image for resize/reformat: bucket=%s, key=%s", event.S3Bucket, event.S3Key)

	s3Object, err := s3Client.GetObject(ctx, &s3.GetObjectInput{
		Bucket: &event.S3Bucket,
		Key:    &event.S3Key,
	})
	if err != nil {
		return ResizeResult{}, fmt.Errorf("failed to get object from S3: %w", err)
	}
	defer func(Body io.ReadCloser) {
		err := Body.Close()
		if err != nil {

		}
	}(s3Object.Body)

	imageBuffer, err := io.ReadAll(s3Object.Body)
	if err != nil {
		return ResizeResult{}, fmt.Errorf("failed to read image from S3 stream: %w", err)
	}

	image, err := vips.NewImageFromBuffer(imageBuffer, nil)
	if err != nil {
		return ResizeResult{}, fmt.Errorf("failed to process image with vips: %w", err)
	}
	defer image.Close()

	// Resize selected image
	if event.Width > 8000 || event.Height > 8000 {
		log.Printf("Image is too large (%dx%d). Creating thumbnail with width 8000px.", event.Width, event.Height)

		options := &vips.ThumbnailImageOptions{
			Height: 4000,
			Crop:   vips.InterestingNone,
		}

		err = image.ThumbnailImage(4000, options)
		if err != nil {
			return ResizeResult{}, fmt.Errorf("failed to create thumbnail with ThumbnailImage: %w", err)
		}
	}

	jpegOptions := &vips.JpegsaveBufferOptions{
		Q:              75,
		OptimizeCoding: true,
		SubsampleMode:  vips.SubsampleAuto,
		TrellisQuant:   true,
	}
	processedBuffer, err := image.JpegsaveBuffer(jpegOptions)
	if err != nil {
		return ResizeResult{}, fmt.Errorf("failed to encode image to JPEG: %w", err)
	}
	log.Printf("Image successfully processed to JPEG. New size: %d bytes", len(processedBuffer))

	newKey := replaceExtensionWithSuffix(event.S3Key, "-processed.jpg")
	_, err = s3Client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:      aws.String(event.S3Bucket),
		Key:         aws.String(newKey),
		Body:        bytes.NewReader(processedBuffer),
		ContentType: aws.String("image/jpeg"),
	})
	if err != nil {
		return ResizeResult{}, fmt.Errorf("failed to upload processed image to S3: %w", err)
	}
	log.Printf("Successfully uploaded processed image to: %s", newKey)

	return ResizeResult{
		Status:       "SUCCESS",
		S3Bucket:     event.S3Bucket,
		OriginalKey:  event.S3Key,
		S3Key:        newKey,
		ImageFormat:  event.ImageFormat,
		Width:        event.Width,
		Height:       event.Height,
		FileSize:     event.FileSize,
		LastModified: event.LastModified,
		ContentType:  event.ContentType,
		UserMetadata: event.UserMetadata,
	}, nil
}

func main() {
	lambda.Start(HandleRequest)
}

// Function to save image in target folder destination
func replaceExtensionWithSuffix(key, suffix string) string {
	ext := filepath.Ext(key)
	if ext == "" {
		return key + suffix
	}
	return key[0:len(key)-len(ext)] + suffix
}
