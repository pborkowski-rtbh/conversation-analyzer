# Local Grafana for iterating on the quality dashboard (§8.8) over the emulator. The plugin is installed at build time,
# because at run time Grafana trusts only the local proxy's certificate and cannot reach the internet.
FROM grafana/grafana:12.2.1
ENV GF_PATHS_PLUGINS=/opt/grafana-plugins
USER root
RUN mkdir -p /opt/grafana-plugins && grafana cli --pluginsDir /opt/grafana-plugins plugins install grafana-bigquery-datasource 3.2.0 \
    && chown -R grafana:root /opt/grafana-plugins
USER grafana
