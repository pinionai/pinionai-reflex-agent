PinionAI Reflex Agent

Launch and test locally:

Start the development server. This command fires up both the FastAPI backend and the Next.js/React frontend with hot-reloading enabled (changes you save to the code will immediately reflect in the browser without dropping states):

- local development

```bash
reflex run
```

```bash
reflex run --frontend-port 9090 --backend-port 8001
```

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

#### Considerations

Instead of typing keys into configuration scripts, you upload them to Google's encrypted vault. Run these commands in your terminal (or use the Google Cloud Console UI) to create your secret slots:

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
# Env var names are case-sensitive and the app reads them in lowercase
# (host_url, agent_id, ...). Do not set PUBLIC_URL: the app serves everything
# on one port and the browser connects back to whatever URL it loaded from.
# Non-sensitive variables go in --set-env-vars; credentials come from Secret Manager.
gcloud run deploy pinion-reflex-chat \
    --image gcr.io/YOUR_PROJECT_ID/pinion-reflex-chat \
    --region us-central1 \
    --no-cpu-throttling \
    --session-affinity \
    --timeout=3600 \
    --set-env-vars host_url="https://pinionai.com",version="live",agent_id="YOUR_AGENT_ID",GCP_PROJECT="YOUR_PROJECT_ID",GCP_REGION="us-central1" \
    --set-secrets client_secret=PINION_CLIENT_SECRET:latest,client_id=PINION_CLIENT_ID:latest
```

The image runs `reflex run --env prod --single-port` on `$PORT` (8080), so the
frontend, websocket and uploads share one port. With `GCP_PROJECT`/`GCP_REGION`,
Gemini authenticates as the Cloud Run service account, which needs the
Vertex AI User role. Alternatively provide `GEMINI_API_KEY` as a secret.

###

Build and Deploy This to Cloud Run

Using the Google Cloud SDK (gcloud), you can build this container in the cloud using Google Cloud Build and deploy it directly to Cloud Run with a single sequence of commands.
Run these commands in your terminal from your project's root folder:
bash

# 1. Submit your project code to Google Cloud Build to create the Docker Image

gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/pinion-reflex-chat

# 2. Deploy the built container to Cloud Run

gcloud run deploy pinion-reflex-chat \
 --image gcr.io/YOUR_PROJECT_ID/pinion-reflex-chat \
 --platform managed \
 --region us-central1 \
 --allow-unauthenticated \
 --no-cpu-throttling \
 --session-affinity \
 --timeout=3600 \
 --set-env-vars host_url="https://pinionai.com",version="live",agent_id="YOUR_AGENT_ID",GCP_PROJECT="YOUR_PROJECT_ID",GCP_REGION="us-central1" \
 --set-secrets client_secret=PINION_CLIENT_SECRET:latest,client_id=PINION_CLIENT_ID:latest

Critical Cloud Run Performance Flags Used Here:

- --no-cpu-throttling: This turns on the "CPU Always Allocated" feature. This is absolutely vital for your app because it prevents Cloud Run from freezing your asynchronous gRPC background polling loops (listen_to_grpc_updates) between active user keypresses.
- --session-affinity: Each chat's PinionAI client lives in the memory of the instance that created it, so a browser must keep reaching the same instance. Do not add Redis (`REDIS_URL`) to "fix" this: the client cannot be serialized, so it would be lost after every event.
- --timeout=3600: Increases the request timeout to 1 hour. This ensures long-lived WebSocket chat connections stay alive and don't aggressively drop out if the user takes a brief pause during a chat session.

### Deploying to a Compute Engine VM

If you decide to deploy to a virtual machine (VM) instead, Docker Compose is actually highly useful here.
A Compute Engine VM is just a blank Linux operating system. It does not automatically route traffic or handle port configurations for you. If you don't use Docker Compose on a VM, the app would be served over plain HTTP on port 8080.
`docker compose up` runs the app on port 8080 by itself. To serve it over HTTPS,
put the included Caddyfile in front of it (replace `:9090` with your domain so
Caddy provisions a certificate automatically):

1. You only open ports 80/443 on your Google Cloud VM firewall.
2. Caddy terminates TLS and proxies everything, including the websocket, to `reflex-app:8080`.

## AI Notes:

Yes, the Dockerfile needed to change. Neither the old Docker setup nor the old Cloud Run setup could serve the app. I've rebuilt it around running everything on one port, and rehearsed the image's build and start steps locally. I couldn't build an actual image because Docker Desktop isn't running.

### Why the old setup couldn't work

1. **The start command can't run.** In Reflex 0.9, production mode requires the frontend and backend on the same port. I ran the old command: it exits immediately with "In prod mode, frontend and backend must run on the same port."
2. **The final image had no Node.** `reflex run --env prod` always rebuilds the frontend when it starts, and the second build stage left Node out. The frontend built in the first stage was thrown away anyway.
3. **Cloud Run settings pointed the browser at the wrong place.** `PUBLIC_URL="https://run.app"` would send every browser to the wrong host. The README also set uppercase `HOST_URL`/`CLIENT_SECRET`, but the code reads lowercase `host_url` etc., and Linux environment variables are case-sensitive, so they'd never be picked up.

## What I changed

- **[Dockerfile](Dockerfile):** one build stage that keeps Node. It does a production build of the frontend at image build time, then starts with `reflex run --env prod --single-port` on `$PORT`. Frontend, live connection and uploads all share that one port, which is how Cloud Run works.
- **[rxconfig.py](rxconfig.py):** the backend URL is only set if you explicitly provide `PUBLIC_URL` or `BACKEND_URL`. Otherwise the page connects back to whatever host it was loaded from, and uses `wss://` under HTTPS. So Cloud Run needs no URL setting.
- **[docker-compose.yml](docker-compose.yml):** a single service on port 8080, plus the Gemini settings (`GCP_PROJECT`, `GCP_REGION`, `GEMINI_API_KEY`).
- **[Caddyfile](Caddyfile):** cut down to one proxy target. It's now optional, only for HTTPS when you deploy to a VM.
- **[README.md](README.md):** fixed the deploy command (lowercase names, Gemini settings, no `PUBLIC_URL`, added `--session-affinity`) and rewrote the VM section.

## How I tested it

On a clean copy of the project, with Cloud Run's environment variable set and no credentials:

- The build step works without a separate `reflex init`.
- The start command takes about 6 seconds, including the frontend rebuild.
- The page, backend health check and upload route all respond on the one port.

## Recommendations

- **Don't add Redis.** Each chat's PinionAI client lives in server memory and can't be saved anywhere else. Without Redis, Reflex runs a single worker per container, which is what keeps the client alive. With Redis it would be lost after every event.
- **Keep `--session-affinity` on Cloud Run** so a browser keeps reaching the instance that holds its chat. If an instance is replaced, the app now creates a new client, but that chat's history is lost.
- **Keep `--no-cpu-throttling`.** The live-agent poller runs in the background between requests and would otherwise freeze.
- **Gemini on Cloud Run:** set `GCP_PROJECT` and `GCP_REGION`, and give the service account the Vertex AI User role. Or supply `GEMINI_API_KEY` from Secret Manager.

I haven't deployed anything. The build pins `python:3.14-slim`, which I haven't tested inside an actual image. The first real build should be a local `docker compose build`.

Yes, that command works as it is. I ran it with your service still on 8080: the app came up at http://localhost:9090, the backend on 8001, and the page's live connection pointed at `ws://localhost:8001/_event`. I've stopped my test instance.

It works because:

- The `--frontend-port` and `--backend-port` flags take priority over `PORT=8080` in your `.env`.
- Since the earlier `rxconfig.py` fix, the backend URL follows whatever `--backend-port` you pass. Before that fix it was stuck at `localhost:8000`, so this exact command would have shown a page with no chat.

Some variants that will clash with your 8080 service:

- **Plain `reflex run` with no flags** reads `PORT=8080` from `.env` and fails with "port in use". Either keep passing the flags, or change `PORT` in `.env` to something free like 9090.
- **Production mode** needs one port for both parts, so pass a single port: `reflex run --env prod --single-port --frontend-port 9090`.
- **Docker Compose** publishes `8080:8080`, which would also collide. Change the left-hand number in [docker-compose.yml](docker-compose.yml), e.g. `"9090:8080"`, and open http://localhost:9090. Keep the right side at 8080, because that's the port inside the container.
