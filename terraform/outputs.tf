output "app_url" {
  description = "Public URL of the Gallery application"
  value       = "http://${google_compute_address.gallery_ip.address}:${var.app_port}"
}

output "vm_external_ip" {
  description = "External IP address of the VM"
  value       = google_compute_address.gallery_ip.address
}

output "db_private_ip" {
  description = "Private IP address of the existing Cloud SQL instance"
  value       = data.google_sql_database_instance.project3.private_ip_address
  sensitive   = true
}

output "db_connection_name" {
  description = "Cloud SQL connection name"
  value       = data.google_sql_database_instance.project3.connection_name
}

output "service_account_email" {
  description = "Email of the Gallery app service account"
  value       = google_service_account.gallery_sa.email
}

output "health_check_url" {
  description = "Health check endpoint"
  value       = "http://${google_compute_address.gallery_ip.address}:${var.app_port}/health"
}
