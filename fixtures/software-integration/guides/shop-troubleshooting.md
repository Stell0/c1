# Shop integration troubleshooting

## Invoice creation fails

Check that the shop sends the `customer` field and a positive `amount` to `POST /invoices`.

## Applicability

This procedure does not apply to Shop 2.1, which renamed the field to `customer_id`.
