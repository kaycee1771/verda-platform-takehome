{{- define "platformDemo.labels" -}}
app.kubernetes.io/name: platform-demo
app.kubernetes.io/instance: platform-demo
app.kubernetes.io/component: demonstrator
app.kubernetes.io/part-of: platform-demo
app.kubernetes.io/managed-by: Helm
platform.verda-demo.io/environment: {{ .Values.environment | quote }}
platform.verda-demo.io/owner: platform-operations
{{- end -}}

{{- define "platformDemo.assertEnvironment" -}}
{{- $namespaces := dict "dev" "demo-dev" "staging" "demo-staging" "prod" "demo-prod" -}}
{{- $replicas := dict "dev" 1 "staging" 1 "prod" 2 -}}
{{- if not (hasKey $namespaces .Values.environment) -}}
{{- fail "environment must be exactly dev, staging, or prod" -}}
{{- end -}}
{{- if ne .Values.namespace (index $namespaces .Values.environment) -}}
{{- fail "namespace does not match the selected environment" -}}
{{- end -}}
{{- if ne .Release.Namespace .Values.namespace -}}
{{- fail "Helm release namespace must equal the accepted environment namespace" -}}
{{- end -}}
{{- if ne (int .Values.replicas) (int (index $replicas .Values.environment)) -}}
{{- fail "replica count must be dev=1, staging=1, prod=2" -}}
{{- end -}}
{{- if not (regexMatch (printf "^platform-%s\\.([0-9]{1,3}-){3}[0-9]{1,3}\\.nip\\.io$" .Values.environment) .Values.hostname) -}}
{{- fail "hostname must be platform-<environment>.<IPv4-with-dashes>.nip.io" -}}
{{- end -}}
{{- $encoded := trimSuffix ".nip.io" (trimPrefix (printf "platform-%s." .Values.environment) .Values.hostname) -}}
{{- range $octet := splitList "-" $encoded -}}
  {{- if or (lt (atoi $octet) 0) (gt (atoi $octet) 255) -}}
  {{- fail "hostname contains an invalid IPv4 octet" -}}
  {{- end -}}
{{- end -}}
verified
{{- end -}}

{{- define "platformDemo.assertActivation" -}}
{{- include "platformDemo.assertEnvironment" . -}}
{{- if not .Values.certificate.bootstrapEnabled -}}
{{- fail "activation is blocked until the staging certificate bootstrap is enabled" -}}
{{- end -}}
{{- if not .Values.certificate.stagingCertificateVerified -}}
{{- fail "activation is blocked until the exact staging Certificate is verified" -}}
{{- end -}}
{{- if not .Values.activation.imageDigestLocked -}}
{{- fail "activation is blocked until the Harbor application digest is locked" -}}
{{- end -}}
{{- if not .Values.activation.pullSecretReady -}}
{{- fail "activation is blocked until platform-demo-registry is Ready" -}}
{{- end -}}
{{- if not .Values.activation.serviceMonitorCRDReady -}}
{{- fail "activation is blocked until the ServiceMonitor CRD and operator are Ready" -}}
{{- end -}}
{{- if not (regexMatch "^sha256:[0-9a-f]{64}$" .Values.image.digest) -}}
{{- fail "application image must use an immutable sha256 digest without a tag" -}}
{{- end -}}
{{- if regexMatch "^sha256:0{64}$" .Values.image.digest -}}
{{- fail "application image digest cannot be the all-zero sentinel" -}}
{{- end -}}
verified
{{- end -}}
