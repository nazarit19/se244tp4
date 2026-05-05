# Service Account (least-privilege)
resource "google_service_account" "gallery_sa" {
  account_id   = "gallery-app-sa"
  display_name = "Gallery App Service Account"
  project      = var.project_id
}

# IAM: Cloud SQL Client
resource "google_project_iam_member" "sa_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.gallery_sa.email}"
}

# IAM: Storage Object Admin (required for photo uploads)
resource "google_project_iam_member" "sa_storage_viewer" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.gallery_sa.email}"
}

# IAM: Log Writer
resource "google_project_iam_member" "sa_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.gallery_sa.email}"
}

# IAM: Secret Manager Accessor (needed since app uses USE_SECRET_MANAGER=true)
resource "google_project_iam_member" "sa_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.gallery_sa.email}"
}


