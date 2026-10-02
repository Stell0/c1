# Ledger operations guide 1.0

Applies to Ledger 1.0 together with Shop 2.0.

## Configuration

Set `ledger_url` to the base URL of the ledger service, for example `http://ledger.test`.

## Creating an invoice

The shop submits an order and calls `POST /invoices` with the `customer` and the `amount`.

## Limitations

Amounts must be positive. Zero amounts are rejected.
