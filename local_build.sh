#!/bin/bash

export REPO=jgruberf5
export APP=f5-container-demo-goldman-sachs
export VERSION=v1

docker build -t $REPO/$APP:latest .
docker build -t $REPO/$APP:$VERSION .

docker push $REPO/$APP:latest
docker push $REPO/$APP:$VERSION
