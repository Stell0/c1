# Invoicing

## Creating an invoice

Call `POST /invoices` with a customer and an amount.

The amount must be greater than zero; zero is rejected with 422.

## Reading an invoice

Call `GET /invoices/{invoiceId}` to read a stored invoice.
