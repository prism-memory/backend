# --- stage 1: go,libavif, libvips setup ---
FROM amazonlinux:2023 AS builder

# ARG TARGETARCH Recommend(arm64)
ARG GO_VERSION=1.24.5
ARG VIPS_VERSION=8.17.1
ARG LIBGAVIF_VERSION=1.3.0
ARG LIBHEIF_VERSION=1.20.1
ARG LIBDE265_VERSION=1.0.16
ARG TARGETARCH

# dependency of go, libavif, libvips
RUN dnf install -y --allowerasing \
    gcc \
    gcc-c++ \
    make \
    pkg-config \
    cmake \
    git \
    nasm \
    svt-av1-devel \
    libdav1d-devel \
    # libheif dependencies
    libtool \
    automake \
    autoconf \
    # libvips dependencies
    glib2-devel \
    expat-devel \
    libjpeg-turbo-devel \
    libpng-devel \
    libtiff-devel \
    libwebp-devel \
    xz \
    gzip \
    meson \
    ninja-build && \
    dnf clean all

# Go 
RUN dnf install -y --allowerasing curl tar gzip && \
    curl -L "https://golang.org/dl/go${GO_VERSION}.linux-${TARGETARCH}.tar.gz" | tar -C /usr/local -zxf -
ENV PATH="/usr/local/go/bin:${PATH}"

ENV VIPS_PREFIX=/opt/vips
ENV PKG_CONFIG_PATH=/opt/vips/lib64/pkgconfig
ENV LD_LIBRARY_PATH=/opt/vips/lib64

# libavif 
RUN git clone --branch v${LIBGAVIF_VERSION} --depth 1 https://github.com/AOMediaCodec/libavif.git && \
    cd libavif && \
    mkdir build && \
    cmake -S . -B build \
    -G "Ninja" \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=ON \
    -DCMAKE_INSTALL_PREFIX=/opt/vips \
    -DAVIF_CODEC_SVT=LOCAL \
    -DAVIF_CODEC_DAV1D=SYSTEM \
    -DAVIF_LIBYUV=LOCAL \
    -DAVIF_JPEG=LOCAL \
    -DAVIF_ZLIBPNG=LOCAL && \
    ninja -C build && \
    ninja -C build install

# libde265 (dependency for libheif HEIC support)
RUN git clone --branch v${LIBDE265_VERSION} --depth 1 https://github.com/strukturag/libde265.git && \
    cd libde265 && \
    mkdir build && \
    cmake -S . -B build \
    -G "Ninja" \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=ON \
    -DCMAKE_INSTALL_PREFIX=${VIPS_PREFIX} && \
    ninja -C build && \
    ninja -C build install

# libheif (dependency for libvips)
# Needs libavif and libde265 to be installed first
RUN git clone --branch v${LIBHEIF_VERSION} --depth 1 https://github.com/strukturag/libheif.git && \
    cd libheif && \
    mkdir build && \
    cmake -S . -B build \
    -G "Ninja" \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=ON \
    -DCMAKE_INSTALL_PREFIX=${VIPS_PREFIX} \
    -DWITH_AVIF=ON \
    -DWITH_SVT=ON \
    -DWITH_DAV1D=ON \
    -DENABLE_PLUGIN_LOADING=OFF && \
    ninja -C build && \
    ninja -C build install

# libvips 
RUN curl -L https://github.com/libvips/libvips/releases/download/v${VIPS_VERSION}/vips-${VIPS_VERSION}.tar.xz | tar -xJvf - && \
    cd vips-${VIPS_VERSION} && \
    meson setup build --prefix=/opt/vips --buildtype=release --default-library=shared \
    -Dheif=enabled \
    -Djpeg=enabled \
    -Dpng=enabled \
    -Dtiff=enabled \
    -Dwebp=enabled \
    -Dintrospection=disabled \
    -Dmagick=disabled \
    -Dpdf=disabled \
    -Dsvg=disabled \
    -Dgif=disabled \
    -Dfuzzing=disabled && \
    ninja -C build -j$(nproc) && \
    ninja -C build test && \
    ninja -C build install

# Go build
WORKDIR /app

# libvips path for CGO
ENV PKG_CONFIG_PATH=/opt/vips/lib64/pkgconfig

# Go module dependency download
COPY go.mod go.sum ./
RUN go mod download

COPY . .

# Go build
RUN CGO_ENABLED=1 GOOS=linux go build -ldflags="-s -w" -o main .


# --- stage 2: lambda setup ---
FROM public.ecr.aws/lambda/provided:al2023

# mininal lib
RUN dnf install -y \
    glib2 \
    expat \
    libjpeg-turbo \
    libpng \
    libtiff \
    libwebp \
    svt-av1-libs \
    libdav1d  && \
    dnf clean all

# get lib from builder
COPY --from=builder /opt/vips/lib64 /opt/vips/lib64

# lib path for system
ENV LD_LIBRARY_PATH=/opt/vips/lib64

# run go
COPY --from=builder /app/main /var/runtime/bootstrap

# Lambda
CMD [ "bootstrap" ]