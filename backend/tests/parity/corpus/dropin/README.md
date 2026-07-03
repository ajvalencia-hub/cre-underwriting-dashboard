# Drop-in parity templates

Put real underwriting templates here to run them through the parity harness —
each in its own folder:

```
dropin/
  my_firm_model/
    template.xlsx   # the real workbook
    mapping.json    # {fieldId: {target, sheet?, ref}} for inputs AND outputs
    inputs.json     # a fully specified deal in input-schema shape
```

Everything in this directory except this README is gitignored — real firm
templates never land in the repo. Run `python -m tests.parity.run` from
`backend/` to see the divergence table.
