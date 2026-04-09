# se422Team4Project1

### Instructions for .env in case anyone needs
1. Create text file and save it named as ".env" in the se422TeamProject1 directory
2. Add the environment variables to the .env file:\
USERNAME = ""\
PASSWORD = ""\
DB_NAME = ""\
BUCKET_NAME=""\
GOOGLE_CLOUD_PROJECT="your-gcp-project-id"\

3. Authenticate to Google Cloud using one of these options:\
Option A: Recommended for organizations that block service-account key creation\
- install Google Cloud CLI\
- run `gcloud auth application-default login`\
- run `gcloud auth application-default set-quota-project your-gcp-project-id`\

Option B: If your organization allows service-account JSON keys\
- set GOOGLE_APPLICATION_CREDENTIALS="/absolute/path/to/service-account.json"\

for first time usage: 
* create python virtual environment 
	1. python3 -m venv .venv
	2. source /pathto/.venv/bin/activate
	3. pip install dependencies: 
		- pymysql
		- flask
		- exifread
		- boto3
		- dotenv
		- google-cloud-storage
* run the flask application in the terminal within the photogallery folder 
	- flask run 
* to run createtable.py
	- python3 /pathto/createtable.py