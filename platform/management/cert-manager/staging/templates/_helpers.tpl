{{- define "verdaCertStaging.hostname" -}}
{{- $hostname := required "hostname must be the accepted argocd.<IPv4-with-dashes>.sslip.io name" .Values.hostname -}}
{{- if not (regexMatch "^argocd\\.[0-9]{1,3}(-[0-9]{1,3}){3}\\.sslip\\.io$" $hostname) -}}
{{- fail "hostname must be the accepted argocd.<IPv4-with-dashes>.sslip.io name" -}}
{{- end -}}
{{- $encoded := trimSuffix ".sslip.io" (trimPrefix "argocd." $hostname) -}}
{{- range $octet := splitList "-" $encoded -}}
{{- if or (lt (atoi $octet) 0) (gt (atoi $octet) 255) -}}
{{- fail "hostname contains an invalid IPv4 octet" -}}
{{- end -}}
{{- end -}}
{{- $hostname -}}
{{- end -}}
