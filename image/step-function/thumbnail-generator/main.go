package main

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"log"
	"path/filepath"
	"strings"
	"sync"

	"github.com/aws/aws-lambda-go/lambda"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/cshum/vipsgen/vips"
)

type ThumbnailEvent struct {
	SourceBucket string `json:"sourceBucket"`
	SourceKey    string `json:"sourceKey"`
}

type ThumbnailResult struct {
	Status        string            `json:"status"`
	OriginalKey   string            `json:"originalKey"`
	ThumbnailKeys map[string]string `json:"thumbnailKeys,omitempty"` // Map of format to its S3 key
	Message       string            `json:"message,omitempty"`
}

var (
	s3Client          *s3.Client
	destinationBucket string
)

func init() {
	cfg, err := config.LoadDefaultConfig(context.TODO())
	if err != nil {
		log.Fatalf("unable to load SDK config, %v", err)
	}
	s3Client = s3.NewFromConfig(cfg)

	vips.Startup(nil)
}

func HandleRequest(ctx context.Context, event ThumbnailEvent) (ThumbnailResult, error) {
	log.Printf("Generating thumbnails for: bucket=%s, key=%s", event.SourceBucket, event.SourceKey)

	destinationBucket = strings.Replace(event.SourceBucket, "originals", "processed", 1)

	s3Object, err := s3Client.GetObject(ctx, &s3.GetObjectInput{
		Bucket: &event.SourceBucket,
		Key:    &event.SourceKey,
	})
	if err != nil {
		return ThumbnailResult{}, fmt.Errorf("failed to get object from S3: %w", err)
	}
	defer func(Body io.ReadCloser) {
		err := Body.Close()
		if err != nil {

		}
	}(s3Object.Body)

	imageBuffer, err := io.ReadAll(s3Object.Body)
	if err != nil {
		return ThumbnailResult{}, fmt.Errorf("failed to read image from S3 stream: %w", err)
	}

	image, err := vips.NewImageFromBuffer(imageBuffer, nil)
	if err != nil {
		return ThumbnailResult{}, fmt.Errorf("failed to process image with vips: %w", err)
	}
	defer image.Close()

	thumbnailOptions := &vips.ThumbnailImageOptions{Crop: vips.InterestingNone}
	err = image.ThumbnailImage(400, thumbnailOptions)
	if err != nil {
		return ThumbnailResult{}, fmt.Errorf("failed to create base thumbnail: %w", err)
	}
	log.Println("Base thumbnail (400px width) created successfully.")

	var wg sync.WaitGroup
	formats := []string{"jpeg", "webp", "avif"}
	results := make(chan map[string]string, len(formats))
	errors := make(chan error, len(formats))

	for _, format := range formats {
		wg.Add(1)
		go processAndUpload(ctx, &wg, image, destinationBucket, event.SourceKey, format, results, errors)
	}

	wg.Wait()
	close(results)
	close(errors)

	for err := range errors {
		if err != nil {
			// Return the first error encountered.
			return ThumbnailResult{}, fmt.Errorf("failed during parallel processing: %w", err)
		}
	}

	// 5. Collect the results from all successful uploads.
	finalKeys := make(map[string]string)
	for result := range results {
		for k, v := range result {
			finalKeys[k] = v
		}
	}

	return ThumbnailResult{
		Status:        "SUCCESS",
		OriginalKey:   event.SourceKey,
		ThumbnailKeys: finalKeys,
	}, nil
}

func processAndUpload(ctx context.Context, wg *sync.WaitGroup, originalImage *vips.Image, bucket, key, format string, results chan<- map[string]string, errors chan<- error) {
	defer wg.Done()

	image, err := originalImage.Copy(nil)
	if err != nil {
		errors <- fmt.Errorf("failed to copy image for %s: %w", format, err)
		return
	}
	defer image.Close()

	var buffer []byte
	var contentType string
	var newKey string

	switch format {
	case "jpeg":
		options := &vips.JpegsaveBufferOptions{Q: 80, OptimizeCoding: true, Interlace: true, SubsampleMode: vips.SubsampleAuto, TrellisQuant: true, OptimizeScans: true}
		buffer, err = image.JpegsaveBuffer(options)
		contentType = "image/jpeg"
		newKey = generateThumbnailKey(key, ".jpg")
	case "webp":
		options := &vips.WebpsaveBufferOptions{Q: 82, Effort: 4, SmartSubsample: true}
		buffer, err = image.WebpsaveBuffer(options)
		contentType = "image/webp"
		newKey = generateThumbnailKey(key, ".webp")
	case "avif":
		options := &vips.HeifsaveBufferOptions{Q: 64, Bitdepth: 8, Effort: 4, Lossless: false, SubsampleMode: vips.SubsampleAuto, Compression: vips.HeifCompressionAv1, Encoder: vips.HeifEncoderSvt}
		buffer, err = image.HeifsaveBuffer(options)
		contentType = "image/avif"
		newKey = generateThumbnailKey(key, ".avif")
	default:
		errors <- fmt.Errorf("unsupported format: %s", format)
		return
	}

	if err != nil {
		errors <- fmt.Errorf("failed to encode to %s: %w", format, err)
		return
	}

	_, err = s3Client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:      aws.String(bucket),
		Key:         aws.String(newKey),
		Body:        bytes.NewReader(buffer),
		ContentType: aws.String(contentType),
	})
	if err != nil {
		errors <- fmt.Errorf("failed to upload %s to S3: %w", format, err)
		return
	}

	log.Printf("Successfully created and uploaded %s thumbnail to s3://%s/%s", format, bucket, newKey)
	results <- map[string]string{format: newKey}
}

// Function to save images in target folder destination
func generateThumbnailKey(originalKey, newExtension string) string {
	dir, filename := filepath.Split(originalKey)
	baseFilename := strings.TrimSuffix(filename, filepath.Ext(filename))
	return filepath.Join(dir, "thumbnail", baseFilename+newExtension)
}

func main() {
	lambda.Start(HandleRequest)
}