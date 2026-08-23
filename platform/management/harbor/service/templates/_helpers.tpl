{{- define "verdaHarbor.hostname" -}}
{{- $hostname := required "harbor.expose.ingress.hosts.core is required" .Values.harbor.expose.ingress.hosts.core -}}
{{- if not (regexMatch "^harbor\\.[0-9]{1,3}(-[0-9]{1,3}){3}\\.sslip\\.io$" $hostname) -}}
{{- fail "Harbor hostname must be harbor.<IPv4-with-dashes>.sslip.io" -}}
{{- end -}}
{{- $encoded := trimSuffix ".sslip.io" (trimPrefix "harbor." $hostname) -}}
{{- range $octet := splitList "-" $encoded -}}
  {{- if or (lt (atoi $octet) 0) (gt (atoi $octet) 255) -}}
    {{- fail "Harbor hostname contains an invalid IPv4 octet" -}}
  {{- end -}}
{{- end -}}
{{- $hostname -}}
{{- end -}}

{{- define "verdaHarbor.assertAdmission" -}}
{{- if not .Values.gates.stagingCertificateVerified -}}
{{- fail "Harbor admission is blocked: set stagingCertificateVerified=true only after the exact staging Certificate is Ready" -}}
{{- end -}}
{{- if not .Values.gates.sealedSecretsReady -}}
{{- fail "Harbor admission is blocked: the seven SealedSecrets must be Ready" -}}
{{- end -}}
{{- if not .Values.gates.postgresqlReady -}}
{{- fail "Harbor admission is blocked: the separately owned PostgreSQL dependency must be Ready" -}}
{{- end -}}
{{- if not .Values.gates.capacityAdmitted -}}
{{- fail "Harbor admission is blocked: steady-state and rollout-peak capacity must be admitted" -}}
{{- end -}}
{{- if not .Values.gates.imageDigestsLocked -}}
{{- fail "Harbor admission is blocked: every active Harbor image digest must be locked" -}}
{{- end -}}
{{- $images := dict
      "portal" .Values.harbor.portal.image.tag
      "core" .Values.harbor.core.image.tag
      "jobservice" .Values.harbor.jobservice.image.tag
      "registry" .Values.harbor.registry.registry.image.tag
      "registryctl" .Values.harbor.registry.controller.image.tag
      "trivy" .Values.harbor.trivy.image.tag
      "valkey" .Values.harbor.redis.internal.image.tag
      "exporter" .Values.harbor.exporter.image.tag -}}
{{- range $name, $reference := $images -}}
  {{- if not (regexMatch "^v?[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$" $reference) -}}
    {{- fail (printf "Harbor admission is blocked: %s image tag must contain an immutable sha256 digest" $name) -}}
  {{- end -}}
  {{- if regexMatch "@sha256:0{64}$" $reference -}}
    {{- fail (printf "Harbor admission is blocked: %s image digest cannot be the all-zero sentinel" $name) -}}
  {{- end -}}
{{- end -}}
{{- $hostname := include "verdaHarbor.hostname" . -}}
{{- if ne .Values.harbor.externalURL (printf "https://%s" $hostname) -}}
{{- fail "Harbor admission is blocked: externalURL must be the exact HTTPS ingress hostname" -}}
{{- end -}}
{{- if or (ne .Values.harbor.database.type "external") (ne .Values.harbor.database.external.existingSecret "harbor-database-credentials") -}}
{{- fail "Harbor admission is blocked: database must use the separately owned existingSecret dependency" -}}
{{- end -}}
{{- if or (ne .Values.harbor.existingSecretAdminPassword "harbor-admin") (ne .Values.harbor.existingSecretSecretKey "harbor-core-secrets") -}}
{{- fail "Harbor admission is blocked: admin and core secrets must use the sealed existingSecret boundary" -}}
{{- end -}}
{{- if .Values.harbor.enableMigrateHelmHook -}}
{{- fail "Harbor admission is blocked: the migration Helm hook is disabled for deterministic Argo ownership" -}}
{{- end -}}
verified
{{- end -}}
