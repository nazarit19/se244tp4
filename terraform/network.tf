# VPC Network
resource "google_compute_network" "gallery_vpc" {
  name                    = var.vpc_name
  auto_create_subnetworks = false
  project                 = var.project_id
}

# Custom Subnet
resource "google_compute_subnetwork" "gallery_subnet" {
  name          = "${var.vpc_name}-subnet"
  ip_cidr_range = var.subnet_cidr
  region        = var.region
  network       = google_compute_network.gallery_vpc.id
  project       = var.project_id
}

# Firewall: Allow HTTP
resource "google_compute_firewall" "allow_http" {
  name    = "${var.vpc_name}-allow-http"
  network = google_compute_network.gallery_vpc.name
  project = var.project_id

  allow {
    protocol = "tcp"
    ports    = ["80"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["gallery-app"]
}

# Firewall: Allow HTTPS
resource "google_compute_firewall" "allow_https" {
  name    = "${var.vpc_name}-allow-https"
  network = google_compute_network.gallery_vpc.name
  project = var.project_id

  allow {
    protocol = "tcp"
    ports    = ["443"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["gallery-app"]
}

# Firewall: Allow app port
resource "google_compute_firewall" "allow_app_port" {
  name    = "${var.vpc_name}-allow-app"
  network = google_compute_network.gallery_vpc.name
  project = var.project_id

  allow {
    protocol = "tcp"
    ports    = [tostring(var.app_port)]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["gallery-app"]
}

# Firewall: Allow SSH (restricted — update source_ranges for production)
resource "google_compute_firewall" "allow_ssh" {
  name    = "${var.vpc_name}-allow-ssh"
  network = google_compute_network.gallery_vpc.name
  project = var.project_id

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["gallery-app"]
}


