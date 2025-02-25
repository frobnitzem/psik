# Using Psik to Launch Jobs at NERSC

Configure a NERSC backend like so,

```
{ "backends": {
    "perlmutter": {
      "type": "nersc",
      "queue_name": "batch",
      "project_name": "m3792",
      "reservation_id": null,
    }
  }
}
```

Keys are read from a file in `$HOME/.superfacility/key.pem`.
The file should have `client_id` in the first line,
followed by a PEM-formatted private key.

Example:

    randmstrgz
    -----BEGIN RSA PRIVATE KEY-----
    ...
    -----END RSA PRIVATE KEY-----

Note the directory permission should be set to `0700` or
the file permission should be `0600`.
