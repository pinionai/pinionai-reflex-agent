PinionAI Reflex Agent

Launch and test locally:

Start the development server. This command fires up both the FastAPI backend and the Next.js/React frontend with hot-reloading enabled (changes you save to the code will immediately reflect in the browser without dropping states):

- Update libraries

```bash
uv pip compile requirements.in -o requirements.txt
uv pip compile --upgrade requirements.in -o requirements.txt
uv pip install -r requirements.txt
```

- local development

This runs the Reflex development server with the frontend on port 9090 and the
backend on port 8001. Activate the Python environment with the project
requirements installed before running it. You can also start the same server
directly with `reflex run --frontend-port 9090 --backend-port 8001`.

```bash
reflex run --frontend-port 9090 --backend-port 8001
```

open your web browser and navigate to:
👉 http://localhost:9090

- As a docker container

```bash
# 1. Build the multi-stage image (This may take a couple of minutes the first time to build the frontend node dependencies)
docker compose build

# 2. Fire up the containers in the foreground to monitor terminal output logs
docker compose up
```

open your web browser and navigate to:
👉 http://localhost:8080

**Cleaning Up**

To stop the environment and shut down the container threads securely, press Ctrl + C in your terminal and execute:

```bash
docker compose down
```

#### Pre-Launch Security Considerations

Instead of typing client_secret keys into environment variable configuration, consider uploading them to Google's encrypted vault. Run these commands in your terminal (or use the Google Cloud Console UI) to create your secret slots:

```bash
# 1. Create a secret container for your Pinion Client Secret
gcloud secrets create PINION_CLIENT_SECRET --replication-policy="automatic"

# 2. Add your actual secret key value into that container
echo -n "your-actual-super-secret-key-here" | gcloud secrets versions add PINION_CLIENT_SECRET --data-file=-
```

Step 2: Grant Cloud Run Access to the Secrets

By default, Cloud Run containers are completely locked down. You must grant your Cloud Run instance permission to read from Secret Manager.

1. Find the Service Account your Cloud Run service uses (usually the Default Compute Service Account).
2. Run this command to grant it the Secret Manager Secret Accessor role specifically for your key:

```bash
gcloud secrets add-iam-policy-binding PINION_CLIENT_SECRET \
    --member="serviceAccount:YOUR_PROJECT_NUMBER-compute@://gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
```

Step 3: Inject Secrets into Your App at Runtime

When you deploy your application container via the gcloud CLI, you instruct Google to fetch the secret from the vault at startup and inject it as a standard system environment variable inside the running container.

```bash
# Non-sensitive variables go in --set-env-vars; credentials come from Secret Manager.
    --set-env-vars host_url="https://pinionai.com",version="",agent_id="YOUR_AGENT_ID" \
    --set-secrets client_secret=PINION_CLIENT_SECRET:latest,client_id=PINION_CLIENT_ID:latest
```

If you choose not to use --set-serets and keep client_id and client_agent as a env variable add `client_id=YOUR_CLIENT_ID_HERE,client_secret=YOUR_CLIENT_SECRET_HERE` to the --set-env-vars

The image runs `reflex run --env prod --single-port` on `$PORT` (8080)

### Cloud Run - Option 1: Build and Deploy This to Cloud Run

Using the Google Cloud SDK (gcloud), you can build this container in the cloud using Google Cloud Build and deploy it directly to Cloud Run with a single sequence of commands.
Run these commands in your terminal from your project's root folder:
bash

# 1. Update Libraries

```bash
uv pip compile requirements.in -o requirements.txt
uv pip compile --upgrade requirements.in -o requirements.txt

uv pip install -r requirements.txt
uv pip sync requirements.txt
```

# 2. EXPORT build variables

```bash
export PROJECT_ID=$(gcloud config get-value project)
export REGION="us-central1" # Or your preferred region
export REPOSITORY="pinion-reflex-chat-repo"
export IMAGE_NAME="pinion-reflex-chat"

gcloud auth configure-docker ${REGION}-docker.pkg.dev

export IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${IMAGE_NAME}:latest"
```

### 2.5. Create an Artifact Registry Repository (only need to do this once)

Create a Docker repository in Artifact Registry to host your container image.

```bash
gcloud artifacts repositories create ${REPOSITORY} \
    --repository-format=docker \
    --location=${REGION} \
    --description="Docker repository for the PINION AI Reflex Chat application"
```

# 3. Submit your project code to Google Cloud Build to create the Docker Image

```bash
gcloud builds submit --tag ${IMAGE_URI}
```

# 4. Deploy the built container to Cloud Run

```bash
gcloud run deploy ${IMAGE_NAME} \
    --image=${IMAGE_URI} \
    --port=8080 \
    --service-account=${SERVICE_ACCOUNT_EMAIL} \
    --project=${PROJECT_ID} \
    --region=${REGION} \
    --platform managed \
    --region us-central1 \
    --allow-unauthenticated \
    --no-cpu-throttling \
    --session-affinity \
    --timeout=3600 \
    --min-instances 0 \
    --memory 2Gi \
    --set-env-vars host_url="https://pinionai.com",version="",agent_id="YOUR_AGENT_ID" \
    --set-secrets client_secret=PINION_CLIENT_SECRET:latest,client_id=PINION_CLIENT_ID:latest
```

_OR_

# 3. USE the Deploy/Prod env.yaml file

```bash
gcloud run deploy ${IMAGE_NAME} \
    --image=${IMAGE_URI} \
    --port=8080 \
    --service-account=${SERVICE_ACCOUNT_EMAIL} \
    --project=${PROJECT_ID} \
    --region=${REGION} \
    --platform managed \
    --allow-unauthenticated \
    --no-cpu-throttling \
    --session-affinity \
    --timeout=3600 \
    --min-instances 0 \
    --memory 2Gi \
    --env-vars-file deploy/prod/env.yaml
```

- Add this if using secrets manager: --set-secrets client_secret=PINION_CLIENT_SECRET:latest,client_id=PINION_CLIENT_ID:latest

#### Critical Cloud Run Performance Flags Used Here:

- --no-cpu-throttling: This turns on the "CPU Always Allocated" feature. This is absolutely vital for your app because it prevents Cloud Run from freezing your asynchronous gRPC background polling loops (listen_to_grpc_updates) between active user keypresses.
- --session-affinity: Each chat's PinionAI client lives in the memory of the instance that created it, so a browser must keep reaching the same instance. Do not add Redis (`REDIS_URL`) to "fix" this: the client cannot be serialized, so it would be lost after every event.
- --timeout=3600: Increases the request timeout to 1 hour. This ensures long-lived WebSocket chat connections stay alive and don't aggressively drop out if the user takes a brief pause during a chat session.
- --min-instances: Allowing for miniimum instances to spin down to 0, saves on cost while developing, but is not recommended for production. It will increase cold starts and spin up time substantially, and not recommended for production.

### Option 2: Deploying to a Compute Engine VM

If you decide to deploy to a virtual machine (VM) instead, Docker Compose is actually highly useful here.
A Compute Engine VM is just a blank Linux operating system. It does not automatically route traffic or handle port configurations for you. If you don't use Docker Compose on a VM, the app would be served over plain HTTP on port 8080.
`docker compose up` runs the app on port 8080 by itself. To serve it over HTTPS,
put the included Caddyfile in front of it (replace `:9090` with your domain so
Caddy provisions a certificate automatically):

1. You only open ports 80/443 on your Google Cloud VM firewall.
2. Caddy terminates TLS and proxies everything, including the websocket, to `reflex-app:8080`.

## Other Notes:

- **[Dockerfile](Dockerfile):** one build stage that keeps Node. It does a production build of the frontend at image build time, then starts with `reflex run --env prod --single-port` on `$PORT`. Frontend, live connection and uploads all share that one port, which is how Cloud Run works.
- **[rxconfig.py](rxconfig.py):** the backend URL is only set if you explicitly provide `PUBLIC_URL` or `BACKEND_URL`. Otherwise the page connects back to whatever host it was loaded from, and uses `wss://` under HTTPS. So Cloud Run needs no URL setting.
- **[Caddyfile](Caddyfile):** cut down to one proxy target. It's now optional, only for HTTPS when you deploy to a VM.

## Recommendations

- **Don't add Redis.** Each chat's PinionAI client lives in server memory and can't be saved anywhere else. Without Redis, Reflex runs a single worker per container, which is what keeps the client alive. With Redis it would be lost after every event.
- **Keep `--session-affinity` on Cloud Run** so a browser keeps reaching the instance that holds its chat. If an instance is replaced, the app now creates a new client, but that chat's history is lost.
- **Keep `--no-cpu-throttling`.** The live-agent poller runs in the background between requests and would otherwise freeze.

The local app comes up at http://localhost:9090, the backend on 8001, and the page's live connection pointed at `ws://localhost:8001/_event`, since you may have local services already running on 8080

Some variants that will clash with other 8080 local test service:

- **Plain `reflex run` with no flags** reads `PORT=8080` from `.env` and fails with "port in use". Either keep passing the flags, or change `PORT` in `.env` to something free like 9090.
- **Production mode** needs one port for both parts, so pass a single port: `reflex run --env prod --single-port --frontend-port 9090`.

- **Docker Compose** publishes `8080:8080`, which would also collide. Change the left-hand number in [docker-compose.yml](docker-compose.yml), e.g. `"9090:8080"`, and open http://localhost:9090. Keep the right side at 8080, because that's the port inside the container.
