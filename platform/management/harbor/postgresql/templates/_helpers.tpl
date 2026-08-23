{{- define "verdaHarborPostgresql.labels" -}}
app.kubernetes.io/name: harbor-postgresql
app.kubernetes.io/instance: harbor-postgresql
app.kubernetes.io/component: database
app.kubernetes.io/part-of: harbor
app.kubernetes.io/managed-by: Helm
{{- end -}}

{{- define "verdaHarborPostgresql.assertAdmission" -}}
{{- if not .Values.gates.sealedCredentialsReady -}}
{{- fail "PostgreSQL admission is blocked until the database SealedSecret is Ready" -}}
{{- end -}}
{{- if not .Values.gates.imageDigestLocked -}}
{{- fail "PostgreSQL admission is blocked until the official image digest is locked" -}}
{{- end -}}
{{- if not (regexMatch "^15\\.10-bookworm@sha256:[0-9a-f]{64}$" .Values.image.tag) -}}
{{- fail "PostgreSQL image must be the pinned 15.10-bookworm tag with an immutable sha256 digest" -}}
{{- end -}}
{{- if regexMatch "@sha256:0{64}$" .Values.image.tag -}}
{{- fail "PostgreSQL image digest cannot be the all-zero sentinel" -}}
{{- end -}}
verified
{{- end -}}
