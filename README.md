🚀 Cloud Run Deployment Instructions



Build Docker Image



gcloud builds submit \\

&nbsp; --tag us-central1-docker.pkg.dev/rive-agents-sandbox/brand-repo/brand-agent:latest



Deploy to Cloud Run



gcloud run deploy brand-agent \\

&nbsp; --image us-central1-docker.pkg.dev/rive-agents-sandbox/brand-repo/brand-agent:latest \\

&nbsp; --region us-central1 \\

&nbsp; --memory 2Gi \\

&nbsp; --cpu 2 \\

&nbsp; --concurrency 1 \\

&nbsp; --timeout 900 \\

&nbsp; --port 8080 \\

&nbsp; --set-env-vars GOOGLE\_API\_KEY="YOUR\_GOOGLE\_API\_KEY"



View Logs



gcloud run services logs read brand-agent --region us-central1

