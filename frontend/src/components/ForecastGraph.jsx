import React, { useEffect, useRef, memo, useState } from 'react';
import { select } from 'd3-selection';
import { zoom, zoomIdentity } from 'd3-zoom';
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide } from 'd3-force';
import { drag } from 'd3-drag';
import './ForecastGraph.css';

const ForecastGraph = memo(function ForecastGraph({ graphData, targetEventId }) {
  const svgRef = useRef(null);
  const containerRef = useRef(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });

  // Handle resizing
  useEffect(() => {
    if (!containerRef.current) return;

    const updateDimensions = () => {
      if (containerRef.current) {
        setDimensions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight
        });
      }
    };

    updateDimensions();

    const observer = new ResizeObserver(updateDimensions);
    observer.observe(containerRef.current);

    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!graphData || !graphData.events || !graphData.hypotheses || dimensions.width === 0 || dimensions.height === 0) {
      return;
    }

    const { width, height } = dimensions;

    try {
      const svg = select(svgRef.current);
      svg.selectAll('*').remove(); // Clear previous graph

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

      // Set up SVG groups
      const g = svg.append('g');

      // Define zoom behavior
      const zoomBehavior = zoom()
        .scaleExtent([0.1, 4])
        .on('zoom', (event) => {
          g.attr('transform', event.transform);
        });

      svg.call(zoomBehavior);

      // Create force simulation
      const simulation = forceSimulation(nodes)
        .force('link', forceLink(links).id(d => d.id).distance(150))
        .force('charge', forceManyBody().strength(-400))
        .force('center', forceCenter(width / 2, height / 2))
        .force('collision', forceCollide().radius(20)); // Increased collision radius

      // Add arrow markers
      svg.append('defs').selectAll('marker')
        .data(['causes', 'enables', 'prevents', 'correlates_with', 'conditional'])
        .join('marker')
        .attr('id', d => `arrow-${d}`)
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 18) // Adjusted for node radius
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
        .attr('stroke-width', d => Math.max(1.5, d.strength * 3))
        .attr('stroke-opacity', 0.8)
        .attr('marker-end', d => `url(#arrow-${d.relation_type})`);

      // Draw nodes
      const node = g.append('g')
        .selectAll('circle')
        .data(nodes)
        .join('circle')
        .attr('r', d => d.id === targetEventId ? 10 : 7) // Larger for target
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
        .attr('stroke', d => d.id === targetEventId ? '#f59e0b' : '#fff') // Gold for target
        .attr('stroke-width', d => d.id === targetEventId ? 3 : 2)
        .style('cursor', 'pointer')
        .style('filter', d => d.id === targetEventId ? 'drop-shadow(0px 0px 8px rgba(245, 158, 11, 0.6))' : 'drop-shadow(0px 1px 3px rgba(0,0,0,0.2))')
        .call(drag()
          .on('start', dragStarted)
          .on('drag', dragged)
          .on('end', dragEnded));

      // Label group
      const labels = g.append('g')
        .selectAll('text')
        .data(nodes)
        .join('text')
        .text(d => d.title.length > 25 ? d.title.substring(0, 25) + '...' : d.title)
        .attr('dy', 20)
        .attr('text-anchor', 'middle')
        .attr('font-size', d => d.id === targetEventId ? 12 : 10)
        .attr('font-weight', d => d.id === targetEventId ? '700' : '500')
        .attr('fill', d => d.id === targetEventId ? '#333' : '#495057')
        .style('pointer-events', 'none')
        .style('text-shadow', '0 1px 3px rgba(255, 255, 255, 0.8)');

      // Tooltips
      const tooltip = select('body').select('.forecast-graph-tooltip');
      // If tooltip doesn't exist (it might persist), select valid one or create
      // Because we remove tooltip in cleanup, we should be fine creating a new one or reusing carefully
      let tooltipDiv = select('body').selectAll('.forecast-graph-tooltip').filter(function () {
        return this.style.display !== 'none';
      });

      if (tooltipDiv.empty()) {
        tooltipDiv = select('body').append('div')
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
      }

      node.on('mouseover', function (event, d) {
        select(this)
          .attr('r', d.id === targetEventId ? 12 : 9)
          .attr('stroke-width', 3);

        tooltipDiv.style('visibility', 'visible')
          .html(`
          <div style="font-size: 14px; font-weight: 600; margin-bottom: 6px; color: #333;">
            ${d.id === targetEventId ? '🎯 ' : ''}${d.title}
          </div>
          <div style="color: #666; margin-bottom: 6px;"><em>${d.domain}</em></div>
          <div style="color: #555; font-size: 12px;">${d.description || ''}</div>
        `);
      })
        .on('mousemove', function (event) {
          tooltipDiv.style('top', (event.pageY - 10) + 'px')
            .style('left', (event.pageX + 10) + 'px');
        })
        .on('mouseout', function (event, d) {
          select(this)
            .attr('r', d.id === targetEventId ? 10 : 7)
            .attr('stroke-width', d.id === targetEventId ? 3 : 2);
          tooltipDiv.style('visibility', 'hidden');
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

        labels
          .attr('x', d => d.x)
          .attr('y', d => d.y);
      });

      // Auto-center on target after simulation settles a bit
      // Auto-center on target after simulation settles a bit
      setTimeout(() => {
        let targetNode = null;
        if (targetEventId) {
          targetNode = nodes.find(n => n.id === targetEventId);
        }

        if (targetNode) {
          // Calculate transform to center targetNode
          const scale = 1.2;
          const x = -targetNode.x * scale + width / 2;
          const y = -targetNode.y * scale + height / 2;

          svg.transition().duration(1000)
            .call(zoomBehavior.transform, zoomIdentity.translate(x, y).scale(scale));
        }
      }, 800);

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
        tooltipDiv.remove();
        simulation.stop();
      };
    } catch (error) {
      console.error('ForecastGraph rendering error:', error);
    }
  }, [graphData, dimensions, targetEventId]);

  if (!graphData || !graphData.events || graphData.events.length === 0) {
    return (
      <div className="forecast-graph-empty">
        <p>No causal reasoning graph available for this forecast.</p>
        <p style={{ fontSize: '14px', color: '#888' }}>
          Enable "Causal Reasoning Tools" when running forecasts to build causal graphs.
        </p>
      </div>
    );
  }

  // Use a flex container for the graph + legend
  return (
    <div ref={containerRef} className="forecast-graph-container" style={{ position: 'relative', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      {/* Legend overlay */}
      <div className="forecast-graph-legend" style={{ position: 'absolute', top: 10, left: 10, zIndex: 10, background: 'rgba(255,255,255,0.8)', padding: '5px' }}>
        <div><span style={{ backgroundColor: '#4CAF50' }}></span> Causes</div>
        <div><span style={{ backgroundColor: '#2196F3' }}></span> Enables</div>
        <div><span style={{ backgroundColor: '#f44336' }}></span> Prevents</div>
        <div><span style={{ backgroundColor: '#FF9800' }}></span> Correlates</div>
        <div><span style={{ backgroundColor: '#9C27B0' }}></span> Conditional</div>
      </div>
      {(dimensions.width > 0 && dimensions.height > 0) && (
        <svg ref={svgRef} width={dimensions.width} height={dimensions.height} style={{ flex: 1, border: 'none', background: 'transparent' }}></svg>
      )}
    </div>
  );
});

export default ForecastGraph;
