import React from 'react';
import {Diagram, DiagramNode, DiagramGroup, DiagramArrow} from './Diagram';

export default function DiagramExamples() {
  return <Diagram title="Anton diagram vocabulary" description="A processing service sends traffic through a flow component. Inside a shared platform boundary, storage supplies a control component. This is a visual vocabulary example, not deployed topology." width={360} height={300}>
    <DiagramNode x={20} y={20} width={130} height={48} label="Processing" role="processing" />
    <DiagramNode x={210} y={20} width={130} height={48} label="Flow" role="flow" />
    <DiagramArrow d="M 150 44 H 208" />
    <DiagramGroup x={20} y={110} width={320} height={170} label="Shared boundary" />
    <DiagramNode x={40} y={165} width={130} height={70} label="Storage" role="storage" shape="storage" />
    <DiagramNode x={200} y={176} width={120} height={48} label="Control" role="control" />
    <DiagramArrow d="M 170 200 H 198" />
  </Diagram>;
}
