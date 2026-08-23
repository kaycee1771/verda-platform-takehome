{{- define "verdaArgocdIngress.assertGates" -}}
{{- if not .Values.gates.productionCertificateVerified -}}
{{- fail "public ingress is blocked until productionCertificateVerified=true is committed after certificate inspection" -}}
{{- end -}}
{{- if not .Values.gates.argocdAuthenticationVerified -}}
{{- fail "public ingress is blocked until argocdAuthenticationVerified=true is committed after negative anonymous and reviewer tests" -}}
{{- end -}}
{{- if not .Values.gates.argocdInternalHttpVerified -}}
{{- fail "public ingress is blocked until argocdInternalHttpVerified=true confirms the restricted Traefik-to-server HTTP boundary" -}}
{{- end -}}
{{- end -}}

{{- define "verdaArgocdIngress.hostname" -}}
{{- $hostname := required "hostname must be the accepted argocd.<IPv4-with-dashes>.nip.io name" .Values.hostname -}}
{{- if not (regexMatch "^argocd\\.[0-9]{1,3}(-[0-9]{1,3}){3}\\.nip\\.io$" $hostname) -}}
{{- fail "hostname must be the accepted argocd.<IPv4-with-dashes>.nip.io name" -}}
{{- end -}}
{{- $encoded := trimSuffix ".nip.io" (trimPrefix "argocd." $hostname) -}}
{{- range $octet := splitList "-" $encoded -}}
{{- if or (lt (atoi $octet) 0) (gt (atoi $octet) 255) -}}
{{- fail "hostname contains an invalid IPv4 octet" -}}
{{- end -}}
{{- end -}}
{{- $hostname -}}
{{- end -}}
