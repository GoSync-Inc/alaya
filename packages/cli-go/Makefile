BINARY=alaya
BUILD_DIR=dist

.PHONY: build test clean fmt vet

build:
	go build -o $(BUILD_DIR)/$(BINARY) ./cmd/alaya/

test:
	go test ./...

fmt:
	gofmt -w .

vet:
	go vet ./...

clean:
	rm -rf $(BUILD_DIR)

install:
	go install ./cmd/alaya/
