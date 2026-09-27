# Auto claims — starter vocabulary

A first draft for motor vehicle claims handling. **Edit it. Do not adopt it as written.**

## Have a claims professional validate it

This ontology uses concepts that are common across motor vehicle claims. It has **not** been reviewed
by a claims professional, and it is not modelled on any particular insurer's process. Before you author
a graph, sit with someone who handles claims and ask three questions:

1. What do you call these things? Rename every class to your own words. A vocabulary a handler does
   not recognize will not be used.
2. What is missing? Reinsurance, fraud referral, litigation, arbitration, complaints and catastrophe
   handling are all absent here.
3. What is one thing here that is actually two? `Party` covers policyholder, claimant, third party,
   witness, repairer and medical provider. That is deliberate for a first draft and is often wrong for
   a real one.

## Jurisdiction: verify before you add

Motor vehicle insurance is regulated locally, and the regulated concepts differ. In Canada, for
example, the province determines much of the product. **Add jurisdiction-specific classes only after
confirming them with someone who knows that jurisdiction**, and cite the instrument you took them from.
Nothing jurisdiction-specific is included here, on purpose: a plausible-sounding wrong class is worse
than a missing one.

Industry data standards exist for insurance messaging and may be a useful source of names. Check what
your organization already uses before inventing terms.

## Personal data: the first thing to decide

A claim file is full of personal data: names, addresses, medical detail, payment details. Decide
**before** ingesting anything:

- Are you ingesting real claim files, or policy wordings, procedures, bulletins and guidelines?
- If real files, what is the lawful basis, and who may query the result?

OTO has a pre-ingest privacy gate that blocks credentials, social insurance numbers and payment cards,
and warns on email, phone, vehicle identification numbers and postal codes. **It is a safety net, not
a review.** It cannot recognize a name, an address or a medical detail written as prose.

The lower-risk start is non-personal material: policy wordings, endorsements, handling procedures,
adjuster guidelines, regulator bulletins, coverage interpretation memos, fraud indicator guidance. That
exercises the whole vocabulary without putting a claimant's file into a searchable index.

## What the shape says

- **`Incident` is separate from `Claim`.** One incident can produce several claims, and a claim is
  reported later than the event. Keeping them apart is what lets you answer "how many claims came out
  of that storm".
- **`Role` is separate from `Party`.** A role is filled by a party, and the filling changes. Attaching
  work to a role rather than a person keeps history correct when the person changes.
- **Money moves in two directions.** `Payment` out and `Recovery` in. Net cost is a question about
  both, and a model with only one cannot answer it.
- **`Decision` is a node, not an attribute.** A decision has a date, a reason, evidence it relied on,
  and it can be superseded. That is exactly what an attribute cannot carry.

## Next

```bash
oto build --project <your project>       # the sample graph compiles as shipped
oto query --project <your project> entity "Claim"
oto ontology check --project <your project>
```

Then replace `sample.graph.json` with your own content, and run `oto ontology accept` once the
vocabulary settles.
