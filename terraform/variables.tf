variable "project_id" {
  description = "The GCP project ID"
  type        = string

  validation {
    condition     = length(var.project_id) > 0
    error_message = "project_id must not be empty."
  }
}

variable "region" {
  description = "The GCP region to deploy resources"
  type        = string
  default     = "us-central1"

  validation {
    condition     = can(regex("^[a-z]+-[a-z]+[0-9]+$", var.region))
    error_message = "region must be a valid GCP region (e.g. us-central1)."
  }
}

variable "zone" {
  description = "The GCP zone to deploy compute resources"
  type        = string
  default     = "us-central1-a"

  validation {
    condition     = can(regex("^[a-z]+-[a-z]+[0-9]+-[a-z]$", var.zone))
    error_message = "zone must be a valid GCP zone (e.g. us-central1-a)."
  }
}

variable "terraform_state_bucket" {
  description = "GCS bucket name for Terraform remote state"
  type        = string

  validation {
    condition     = length(var.terraform_state_bucket) > 0
    error_message = "terraform_state_bucket must not be empty."
  }
}

variable "vpc_name" {
  description = "Name of the VPC network"
  type        = string
  default     = "gallery-vpc"
}

variable "subnet_cidr" {
  description = "CIDR range for the custom subnet"
  type        = string
  default     = "10.0.0.0/16"

  validation {
    condition     = can(cidrnetmask(var.subnet_cidr))
    error_message = "subnet_cidr must be a valid CIDR block."
  }
}

variable "vm_machine_type" {
  description = "Machine type for the Compute Engine VM"
  type        = string
  default     = "e2-standard-2"

  validation {
    condition     = contains(["e2-standard-2", "e2-standard-4", "e2-medium"], var.vm_machine_type)
    error_message = "vm_machine_type must be a valid e2 machine type."
  }
}

variable "vm_image" {
  description = "Boot disk image for the Compute Engine VM"
  type        = string
  default     = "debian-cloud/debian-11"
}

variable "db_instance_name" {
  description = "Name of the existing Cloud SQL instance to connect to"
  type        = string
  default     = "project3"
}

variable "cloud_sql_connection_name" {
  description = "Cloud SQL connection name (project:region:instance)"
  type        = string
  default     = "project-fbc74fdb-f2d5-4f06-935:us-central1:project3"

  validation {
    condition     = can(regex("^[^:]+:[^:]+:[^:]+$", var.cloud_sql_connection_name))
    error_message = "cloud_sql_connection_name must be in format project:region:instance."
  }
}

variable "app_port" {
  description = "Port the Gallery application listens on"
  type        = number
  default     = 3000

  validation {
    condition     = var.app_port > 1024 && var.app_port < 65535
    error_message = "app_port must be between 1025 and 65534."
  }
}

variable "environment" {
  description = "Deployment environment tag"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod."
  }
}
