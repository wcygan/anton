import React from 'react';
import {Diagram, DiagramNode, DiagramGroup, DiagramArrow, type DiagramShape, type DiagramRole} from './index';

const examples: readonly {shape: DiagramShape; label: string; role: DiagramRole; description: string}[] = [
  {shape: 'server', label: 'Server', role: 'control', description: 'A physical bare-metal machine, distinct from a workload.'},
  {shape: 'bucket', label: 'Bucket', role: 'storage', description: 'Object storage, such as an S3 bucket supplied by SeaweedFS.'},
  {shape: 'document', label: 'Manifest', role: 'control', description: 'A configuration file, source manifest, or generated artifact.'},
  {shape: 'client', label: 'Client', role: 'processing', description: 'A browser or client workstation.'},
  {shape: 'volume', label: 'Volume', role: 'storage', description: 'A block volume or physical disk. The label must identify which.'},
  {shape: 'gateway', label: 'Gateway', role: 'flow', description: 'A routing gateway, with distinct input and output edges.'},
  {shape: 'replicas', label: 'Replicas', role: 'processing', description: 'Multiple copies of one logical resource, not partitions or shards.'},
];

export default function ShapeGallery() {
  return <div className="diagram-shape-gallery">
    {examples.map(({shape, label, role, description}) =>
      <Diagram key={shape} title={label} description={description} width={220} height={110}>
        <DiagramNode x={25} y={20} width={170} height={70} shape={shape} role={role} label={label} />
      </Diagram>)}
    <Diagram title="Decision" description="A readiness decision branches to Yes or No; every outgoing branch is explicitly labeled." width={240} height={165}>
      <DiagramNode x={50} y={5} width={140} height={80} shape="decision" role="control" label="Ready?" />
      <DiagramArrow d="M 50 45 H 15 V 130 H 38" />
      <DiagramArrow d="M 190 45 H 225 V 130 H 202" />
      <DiagramNode x={40} y={110} width={64} height={40} role="control" label="Wait" />
      <DiagramNode x={136} y={110} width={64} height={40} role="flow" label="Next" />
      <text className="diagram-label" x={18} y={101}>No</text>
      <text className="diagram-label" x={203} y={101}>Yes</text>
    </Diagram>
    <Diagram title="Ownership boundary" description="A dashed named enclosure groups related resources; the label states whether it represents ownership, a namespace, or a trust boundary." width={220} height={110}>
      <DiagramGroup x={5} y={5} width={210} height={100} label="Namespace" variant="dashed" />
      <DiagramNode x={50} y={48} width={120} height={40} label="Workload" role="processing" />
    </Diagram>
  </div>;
}
