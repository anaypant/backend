variable "project_id" {
  type        = string
  description = "GCP project ID where auth functions and gateways run."
}

variable "region" {
  type        = string
  description = "Region for regional resources (e.g. us-central1)."
}

variable "firebase_web_api_key" {
  type        = string
  sensitive   = true
  description = "Firebase Web API key (Project settings) for Identity Toolkit REST from Cloud Functions."
}

variable "platform_sa_email" {
  type = string
}

variable "google_oauth_client_id" {
  type        = string
  sensitive   = true
  default     = ""
  description = "Optional. Google OAuth Web client ID for Identity Platform Google provider. Leave empty to configure Google sign-in in Firebase Console instead."
}

variable "google_oauth_client_secret" {
  type        = string
  sensitive   = true
  default     = ""
  description = "Optional. Google OAuth client secret (paired with google_oauth_client_id)."
}
