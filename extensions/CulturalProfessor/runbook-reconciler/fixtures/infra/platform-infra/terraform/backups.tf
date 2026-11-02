resource "aws_backup_vault" "payments" {
  name = "meridian-payments-vault"
}

resource "aws_backup_plan" "payments" {
  name = "meridian-payments-daily"

  rule {
    rule_name         = "daily-snapshot"
    target_vault_name = aws_backup_vault.payments.name
    schedule          = "cron(0 3 * * ? *)"

    lifecycle {
      delete_after = 35
    }
  }
}
