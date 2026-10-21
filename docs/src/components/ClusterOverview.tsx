import React from 'react';
import {Diagram, DiagramNode, DiagramGroup, DiagramArrow} from './Diagram';

export default function ClusterOverview() {
  return <>
    <div className="cluster-overview-wide">
      <Diagram title="Internet access to Anton on three bare-metal nodes" description="Internet clients use HTTPS to Cloudflare. Cloudflare Tunnel carries requests into Anton, where cloudflared and Envoy route them to applications. Three physical Talos Linux nodes power Kubernetes." width={740} height={240}>
        <DiagramGroup x={280} y={8} width={452} height={224} label="Anton · Kubernetes" />
        <DiagramNode x={8} y={72} width={110} height={58} role="processing" shape="client" label={["Internet", "clients"]} />
        <DiagramNode x={157} y={72} width={104} height={58} role="flow" label="Cloudflare" />
        <DiagramNode x={306} y={72} width={170} height={58} role="flow" shape="gateway" label={["cloudflared", "→ Envoy"]} />
        <DiagramNode x={536} y={72} width={170} height={58} role="processing" label="Applications" />
        <DiagramArrow d="M 118 101 H 155" />
        <DiagramArrow d="M 261 101 H 304" />
        <DiagramArrow d="M 476 101 H 534" />
        <text x={506} y={166} textAnchor="middle" className="diagram-label">Three physical nodes · Talos Linux</text>
        <DiagramNode x={312} y={182} width={112} height={34} role="control" shape="server" label="Node 1" />
        <DiagramNode x={450} y={182} width={112} height={34} role="control" shape="server" label="Node 2" />
        <DiagramNode x={588} y={182} width={112} height={34} role="control" shape="server" label="Node 3" />
      </Diagram>
    </div>
    <div className="cluster-overview-narrow">
      <Diagram title="Internet access to Anton on three bare-metal nodes" description="Internet clients reach Cloudflare over HTTPS. A tunnel carries requests to cloudflared and Envoy in Anton, which route to applications. Three bare-metal Talos Linux nodes power Kubernetes." width={360} height={490}>
        <DiagramGroup labelAlign="start" x={4} y={162} width={352} height={320} label="Anton · Kubernetes" />
        <DiagramNode x={110} y={5} width={140} height={42} role="processing" shape="client" label="Internet clients" />
        <DiagramNode x={110} y={88} width={140} height={42} role="flow" label="Cloudflare" />
        <DiagramNode x={90} y={207} width={180} height={56} role="flow" shape="gateway" label={["cloudflared", "→ Envoy"]} />
        <DiagramNode x={100} y={315} width={160} height={42} role="processing" label="Applications" />
        <DiagramArrow d="M 180 47 V 86" />
        <DiagramArrow d="M 180 130 V 205" />
        <DiagramArrow d="M 180 263 V 313" />
        <text x={180} y={400} textAnchor="middle" className="diagram-label">Three physical nodes · Talos Linux</text>
        <DiagramNode x={20} y={425} width={100} height={38} role="control" shape="server" label="Node 1" />
        <DiagramNode x={130} y={425} width={100} height={38} role="control" shape="server" label="Node 2" />
        <DiagramNode x={240} y={425} width={100} height={38} role="control" shape="server" label="Node 3" />
      </Diagram>
    </div>
  </>;
}
