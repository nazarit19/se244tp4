# Reference the existing Cloud SQL instance (not managed by Terraform)
data "google_sql_database_instance" "project3" {
  name    = var.db_instance_name
  project = var.project_id
}
