#!/bin/bash

# Define your image name
IMAGE_NAME="listen-wiseer"
CONTAINER_NAME = "listen-wiseer"

# Define the port mapping if applicable
PORT_MAPPING="-p 8000:80"

# Define other options if needed
OTHER_OPTIONS=""

# Run the Docker container
docker run -d $PORT_MAPPING $OTHER_OPTIONS $IMAGE_NAME


#chmod +x docker-run.sh


