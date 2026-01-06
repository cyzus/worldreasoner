import React, { useEffect, useRef, memo } from 'react';
import { select } from 'd3-selection';
import { zoom } from 'd3-zoom';
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide } from 'd3-force';
import { drag } from 'd3-drag';
import './ForecastGraph.css';

const ForecastGraph = memo(function ForecastGraph({ graphData }) {
  const svgRef = useRef(null);
  const containerRef = useRef(null);

  useEffect(() => {
    if (!graphData || !graphData.events || !graphData.hypotheses) {
      return;
    }

    const container = containerRef.current;
    if (!container) {
      return;
    }

    try {
      const svg = select(svgRef.current);
      svg.selectAll('*').remove();

      // Get container width with fallback
      let width = container.clientWidth;
      if (!width || width < 100) {
        width = 400;
      }
      const height = 600;

    // Create nodes from events
    const nodes = graphData.events.map(event => ({
      id: event.id,
      title: event.title,
      domain: event.domain,
      type: 'event',
      ...event
    }));

    // Get all event IDs for validation
    const eventIds = new Set(nodes.map(n => n.id));

    // Create links from hypotheses - filter out broken references
    const links = graphData.hypotheses
      .filter(hyp => {
        const sourceExists = eventIds.has(hyp.source_event_id);
        const targetExists = eventIds.has(hyp.target_event_id);
        return sourceExists && targetExists;
      })
      .map(hyp => ({
        source: hyp.source_event_id,
        target: hyp.target_event_id,
        relation_type: hyp.relation_type,
        strength: hyp.strength,
        confidence: hyp.confidence,
        reasoning: hyp.reasoning,
        ...hyp
      }));

    // Set up SVG
    const g = svg.append('g');

    svg.attr('width', width)
       .attr('height', height);

    // Add zoom behavior
    const zoomBehavior = zoom()
      .scaleExtent([0.1, 4])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });

    svg.call(zoomBehavior);

    // Create force simulation with better spacing
    const simulation = forceSimulation(nodes)
      .force('link', forceLink(links).id(d => d.id).distance(200))
      .force('charge', forceManyBody().strength(-500))
      .force('center', forceCenter(width / 2, height / 2))
      .force('collision', forceCollide().radius(80));

    // Add arrow markers for directed edges
    svg.append('defs').selectAll('marker')
      .data(['causes', 'enables', 'prevents', 'correlates_with', 'conditional'])
      .join('marker')
        .attr('id', d => `arrow-${d}`)
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 25)
        .attr('refY', 0)
        .attr('markerWidth', 6)
        .attr('markerHeight', 6)
        .attr('orient', 'auto')
      .append('path')
        .attr('fill', d => {
          const colors = {
            'causes': '#4CAF50',
            'enables': '#2196F3',
            'prevents': '#f44336',
            'correlates_with': '#FF9800',
            'conditional': '#9C27B0'
          };
          return colors[d] || '#666';
        })
        .attr('d', 'M0,-5L10,0L0,5');

    // Draw links
    const link = g.append('g')
      .selectAll('line')
      .data(links)
      .join('line')
        .attr('stroke', d => {
          const colors = {
            'causes': '#4CAF50',
            'enables': '#2196F3',
            'prevents': '#f44336',
            'correlates_with': '#FF9800',
            'conditional': '#9C27B0'
          };
          return colors[d.relation_type] || '#666';
        })
        .attr('stroke-width', d => Math.max(1, d.strength * 3))
        .attr('stroke-opacity', d => d.confidence)
        .attr('marker-end', d => `url(#arrow-${d.relation_type})`);

    // Draw nodes with better styling
    const node = g.append('g')
      .selectAll('circle')
      .data(nodes)
      .join('circle')
        .attr('r', 25)
        .attr('fill', d => {
          const domainColors = {
            'finance': '#4CAF50',
            'politics': '#2196F3',
            'tech': '#9C27B0',
            'health': '#f44336',
            'climate': '#00BCD4',
            'business': '#FF9800',
            'general': '#757575'
          };
          return domainColors[d.domain] || '#757575';
        })
        .attr('stroke', '#fff')
        .attr('stroke-width', 3)
        .style('cursor', 'pointer')
        .style('filter', 'drop-shadow(0px 2px 4px rgba(0,0,0,0.2))')
        .call(drag()
          .on('start', dragStarted)
          .on('drag', dragged)
          .on('end', dragEnded));

    // Add labels with background for better readability
    const labelGroup = g.append('g')
      .selectAll('g')
      .data(nodes)
      .join('g');

    // Add white background for labels
    labelGroup.append('rect')
      .attr('fill', 'white')
      .attr('stroke', '#ddd')
      .attr('stroke-width', 1)
      .attr('rx', 4)
      .attr('ry', 4)
      .attr('opacity', 0.9);

    // Add text
    const label = labelGroup.append('text')
      .text(d => d.title.length > 35 ? d.title.substring(0, 35) + '...' : d.title)
      .attr('font-size', 13)
      .attr('font-weight', '500')
      .attr('fill', '#333')
      .style('pointer-events', 'none');

    // Position background rectangles based on text size
    labelGroup.each(function(d) {
      const textNode = select(this).select('text').node();
      const bbox = textNode.getBBox();
      select(this).select('rect')
        .attr('x', bbox.x - 4)
        .attr('y', bbox.y - 2)
        .attr('width', bbox.width + 8)
        .attr('height', bbox.height + 4);
    });

    // Add tooltips with better styling
    const tooltip = select('body').append('div')
      .attr('class', 'forecast-graph-tooltip')
      .style('position', 'absolute')
      .style('visibility', 'hidden')
      .style('background-color', 'rgba(255, 255, 255, 0.98)')
      .style('border', '1px solid #ccc')
      .style('border-radius', '8px')
      .style('padding', '12px 16px')
      .style('box-shadow', '0 4px 12px rgba(0,0,0,0.15)')
      .style('max-width', '350px')
      .style('font-size', '13px')
      .style('line-height', '1.5')
      .style('z-index', 10000);

    node.on('mouseover', function(event, d) {
      select(this)
        .attr('r', 30)
        .attr('stroke-width', 4);

      tooltip.style('visibility', 'visible')
        .html(`
          <div style="font-size: 14px; font-weight: 600; margin-bottom: 6px; color: #333;">${d.title}</div>
          <div style="color: #666; margin-bottom: 6px;"><em>${d.domain}</em></div>
          <div style="color: #555; font-size: 12px;">${d.description || ''}</div>
        `);
    })
    .on('mousemove', function(event) {
      tooltip.style('top', (event.pageY - 10) + 'px')
        .style('left', (event.pageX + 10) + 'px');
    })
    .on('mouseout', function() {
      select(this)
        .attr('r', 25)
        .attr('stroke-width', 3);
      tooltip.style('visibility', 'hidden');
    });

    link.on('mouseover', function(event, d) {
      select(this)
        .attr('stroke-width', Math.max(3, d.strength * 4));

      tooltip.style('visibility', 'visible')
        .html(`
          <div style="font-size: 14px; font-weight: 600; margin-bottom: 6px; color: #333; text-transform: capitalize;">${d.relation_type.replace('_', ' ')}</div>
          <div style="margin-bottom: 4px;"><strong>Strength:</strong> ${(d.strength * 100).toFixed(0)}%</div>
          <div style="margin-bottom: 8px;"><strong>Confidence:</strong> ${(d.confidence * 100).toFixed(0)}%</div>
          <div style="color: #555; font-size: 12px; border-top: 1px solid #eee; padding-top: 8px;">${d.reasoning}</div>
        `);
    })
    .on('mousemove', function(event) {
      tooltip.style('top', (event.pageY - 10) + 'px')
        .style('left', (event.pageX + 10) + 'px');
    })
    .on('mouseout', function(event, d) {
      select(this)
        .attr('stroke-width', Math.max(1, d.strength * 3));
      tooltip.style('visibility', 'hidden');
    });

    // Update positions on tick
    simulation.on('tick', () => {
      link
        .attr('x1', d => d.source.x)
        .attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x)
        .attr('y2', d => d.target.y);

      node
        .attr('cx', d => d.x)
        .attr('cy', d => d.y);

      labelGroup
        .attr('transform', d => `translate(${d.x + 30}, ${d.y - 10})`);
    });

    // Drag functions
    function dragStarted(event, d) {
      if (!event.active) simulation.alphaTarget(0.3).restart();
      d.fx = d.x;
      d.fy = d.y;
    }

    function dragged(event, d) {
      d.fx = event.x;
      d.fy = event.y;
    }

    function dragEnded(event, d) {
      if (!event.active) simulation.alphaTarget(0);
      d.fx = null;
      d.fy = null;
    }

    // Cleanup
    return () => {
      tooltip.remove();
    };
    } catch (error) {
      console.error('ForecastGraph rendering error:', error);
    }
  }, [graphData]);

  if (!graphData || !graphData.events || graphData.events.length === 0) {
    return (
      <div className="forecast-graph-empty">
        <p>No causal reasoning graph available for this forecast.</p>
        <p style={{fontSize: '14px', color: '#888'}}>
          Enable "Causal Reasoning Tools" when running forecasts to build causal graphs.
        </p>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="forecast-graph-container">
      <div className="forecast-graph-header">
        <h4>Causal Reasoning Graph</h4>
        <div className="forecast-graph-stats">
          <span>{graphData.events.length} events</span>
          <span>{graphData.hypotheses.length} causal links</span>
        </div>
      </div>
      <div className="forecast-graph-legend">
        <div><span style={{backgroundColor: '#4CAF50'}}></span> Causes</div>
        <div><span style={{backgroundColor: '#2196F3'}}></span> Enables</div>
        <div><span style={{backgroundColor: '#f44336'}}></span> Prevents</div>
        <div><span style={{backgroundColor: '#FF9800'}}></span> Correlates With</div>
        <div><span style={{backgroundColor: '#9C27B0'}}></span> Conditional</div>
      </div>
      <svg ref={svgRef}></svg>
    </div>
  );
});

export default ForecastGraph;
