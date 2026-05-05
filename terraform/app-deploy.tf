# ── Static External IP ────────────────────────────────────────────────────────
resource "google_compute_address" "gallery_ip" {
  name    = "gallery-static-ip"
  region  = var.region
  project = var.project_id
}

# ── Compute Engine VM with cloud-init startup script ─────────────────────────
resource "google_compute_instance" "gallery_vm" {
  name         = "gallery-app-vm"
  machine_type = var.vm_machine_type
  zone         = var.zone
  project      = var.project_id

  tags = ["gallery-app"]

  boot_disk {
    initialize_params {
      image = var.vm_image
      size  = 20
    }
  }

  network_interface {
    network    = google_compute_network.gallery_vpc.id
    subnetwork = google_compute_subnetwork.gallery_subnet.id

    access_config {
      nat_ip = google_compute_address.gallery_ip.address
    }
  }

  service_account {
    email  = google_service_account.gallery_sa.email
    scopes = ["cloud-platform"]
  }

  # Cloud-init script handles:
  # 1. Dependency installation (Python, nginx, Cloud SQL proxy)
  # 2. Application deployment from git
  # 3. Environment configuration
  # 4. Database schema initialization
  # 5. Systemd service setup for automatic restart on boot
  metadata = {
    startup-script = templatefile("${path.module}/scripts/startup.sh", {
      cloud_sql_connection_name = var.cloud_sql_connection_name
      app_port                  = var.app_port
    })
  }

  labels = {
    environment = var.environment
    app         = "gallery"
  }

  depends_on = [
    google_service_account.gallery_sa,
    google_project_iam_member.sa_cloudsql_client,
    google_project_iam_member.sa_secret_accessor,
  ]
}
