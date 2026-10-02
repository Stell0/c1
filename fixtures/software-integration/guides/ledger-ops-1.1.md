# Ledger operations guide 1.1

Applies to Ledger 1.1 together with Shop 2.1.

## Configuration

Set `ledger_url` to the base URL of the ledger service, for example `http://ledger.test`.

## Creating an invoice

The shop submits an order and calls `POST /invoices` with the `customer_id` and the `amount`.
