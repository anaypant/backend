terraform {
  required_version = ">= 1.5"
}

module "core" { source = "./core" }
module "db" { source = "./db" }
module "auth" { source = "./auth" }
module "api" { source = "./api" }
module "integrations" { source = "./integations" }

output "stack" {
  value = {
    core         = module.core.id
    db           = module.db.id
    auth         = module.auth.id
    api          = module.api.id
    integrations = module.integrations.id
  }
}
