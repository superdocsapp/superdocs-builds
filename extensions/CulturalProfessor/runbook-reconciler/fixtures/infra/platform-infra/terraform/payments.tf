provider "aws" {
  region = "eu-west-1"
}

resource "aws_db_instance" "payments" {
  identifier              = "meridian-payments-prod"
  engine                  = "postgres"
  engine_version          = "16.3"
  instance_class          = "db.r6g.2xlarge"
  multi_az                = true
  backup_retention_period = 14
  backup_window           = "03:00-04:00"
  storage_encrypted       = true
}

resource "aws_db_instance" "payments_replica" {
  identifier          = "meridian-payments-prod-replica"
  replicate_source_db = aws_db_instance.payments.identifier
  instance_class      = "db.r6g.xlarge"
}

resource "aws_s3_bucket" "manifest_archive" {
  bucket = "meridian-manifest-archive"
}

resource "aws_s3_bucket_lifecycle_configuration" "manifest_archive" {
  bucket = aws_s3_bucket.manifest_archive.id

  rule {
    id     = "expire-manifests"
    status = "Enabled"

    expiration {
      days = 90
    }
  }
}
