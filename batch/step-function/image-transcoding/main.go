package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/url"
	"os"
	"path/filepath"
	"strings"

	"github.com/aws/aws-lambda-go/lambda"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
	"github.com/cshum/vipsgen/vips"
)

type AvifEncodingOptions struct {
	Quality  int `json:"quality"`
	Effort   int `json:"effort"`
	Bitdepth int `json:"bitdepth"`
}

type TranscodeEvent struct {
	SourceBucket string              `json:"sourceBucket"`
	SourceKey    string              `json:"sourceKey"`
	AvifEncoding AvifEncodingOptions `json:"avifEncoding"`
}


type ConversionResult struct {
	Status      string `json:"status"`
	OriginalKey string `json:"originalKey"`
	NewKey      string `json:"newKey,omitempty"`
	Message     string `json:"message,omitempty"`
}

var s3Client *s3.Client
var destinationBucket string 

func init() {
	cfg, err := config.LoadDefaultConfig(context.TODO(),
		config.WithRegion("ap-northeast-2"),
	)
	if err != nil {
		log.Fatalf("unable to load SDK config, %v", err)
	}
	s3Client = s3.NewFromConfig(cfg)


	destinationBucket = os.Getenv("DESTINATION_BUCKET")
	if destinationBucket == "" {
		log.Fatal("Error: DESTINATION_BUCKET 환경변수가 설정되어야 합니다.")
	}

	vips.Startup(nil)
	log.Println("S3 client and vips initialized successfully")
}

func HandleRequest(ctx context.Context, event TranscodeEvent) (ConversionResult, error) {
	eventBytes, _ := json.Marshal(event)
	log.Printf("Lambda 핸들러 시작. 입력 데이터: %s", string(eventBytes))

	return processImage(ctx, event)
}


func main() {
	lambda.Start(HandleRequest)
}


func processImage(ctx context.Context, event TranscodeEvent) (ConversionResult, error) {

	sourceBucket := event.SourceBucket
	sourceKey := event.SourceKey

	decodedSrcKey, err := url.QueryUnescape(sourceKey)
	if err != nil {
		return ConversionResult{Status: "FAILED", OriginalKey: sourceKey}, fmt.Errorf("failed to decode S3 key: %w", err)
	}
	log.Printf("Processing image: bucket=%s, key=%s", sourceBucket, decodedSrcKey)

	s3Object, err := s3Client.GetObject(ctx, &s3.GetObjectInput{
		Bucket: aws.String(sourceBucket),
		Key:    aws.String(decodedSrcKey),
	})
	if err != nil {
		return ConversionResult{Status: "FAILED", OriginalKey: decodedSrcKey}, fmt.Errorf("failed to get object from S3: %w", err)
	}
	defer func(Body io.ReadCloser) {
		err := Body.Close()
		if err != nil {

		}
	}(s3Object.Body)

	imageBuffer, err := io.ReadAll(s3Object.Body)
	if err != nil {
		return ConversionResult{Status: "FAILED", OriginalKey: decodedSrcKey}, fmt.Errorf("failed to read image from S3 stream: %w", err)
	}
	originalSize := int64(len(imageBuffer))

	image, err := vips.NewImageFromBuffer(imageBuffer, nil)
	if err != nil {
		return ConversionResult{Status: "FAILED", OriginalKey: decodedSrcKey}, fmt.Errorf("failed to process image with vips from buffer: %w", err)
	}
	defer image.Close()

	options := &vips.HeifsaveBufferOptions{
		Q:             event.AvifEncoding.Quality,
		Bitdepth:      event.AvifEncoding.Bitdepth,
		Effort:        event.AvifEncoding.Effort,
		Lossless:      false,
		SubsampleMode: vips.SubsampleAuto,
		Compression:   vips.HeifCompressionAv1,
		Encoder:       vips.HeifEncoderSvt,
	}

	log.Printf("DEBUG: Preparing to export with options: %+v\n", options)
	avifBuffer, err := image.HeifsaveBuffer(options)
	if err != nil {
		return ConversionResult{Status: "FAILED", OriginalKey: decodedSrcKey}, fmt.Errorf("failed to encode image to AVIF: %w", err)
	}
	log.Printf("Successfully encoded to AVIF. Original size: %d bytes, New size: %d bytes", originalSize, len(avifBuffer))

	dir := filepath.Dir(decodedSrcKey)
	filename := filepath.Base(decodedSrcKey)
	newKey := filepath.Join(dir, "originals", filename)
	newKey = replaceExtension(newKey, ".avif")

	log.Printf("Uploading converted image to: bucket=%s, key=%s", destinationBucket, newKey)

	_, err = s3Client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:            aws.String(destinationBucket),
		Key:               aws.String(newKey),
		Body:              bytes.NewReader(avifBuffer),
		ContentType:       aws.String("image/avif"),
		ContentLength:     aws.Int64(int64(len(avifBuffer))),
		ChecksumAlgorithm: types.ChecksumAlgorithmSha256,
	})
	if err != nil {
		return ConversionResult{Status: "FAILED", OriginalKey: decodedSrcKey}, fmt.Errorf("failed to upload AVIF image to S3: %w", err)
	}

	return ConversionResult{
		Status:      "CONVERTED",
		OriginalKey: decodedSrcKey,
		NewKey:      newKey,
	}, nil
}

func replaceExtension(key, newExt string) string {
	ext := filepath.Ext(key)
	if ext == "" {
		return key + newExt
	}
	return strings.TrimSuffix(key, ext) + newExt
}
