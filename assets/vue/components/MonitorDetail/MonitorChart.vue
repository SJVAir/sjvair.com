<script setup lang="ts">
import * as d3 from "d3";
import { inject, onMounted, watchEffect } from "vue";
import {ChartDataPoint} from "../../models";
import { dateUtil } from "../../utils";
import type { D3Service, MonitorsService } from "../../services";
import type { ChartDataArray, ChartDataField } from "../../types";


const d3Service = inject<D3Service>("D3Service")!;
const monitorsService = inject<MonitorsService>("MonitorsService")!;
//import BackgroundTaskClient from "../../webworkers/BackgroundTaskClient";

//const bgtc = new BackgroundTaskClient(new Worker("../../webworkers/ChartDataProcessor.js", { type: "module" }));
 // props: [ "chartData" ],

const margin = {
  top: 24,
  right: 24,
  bottom: 56,
  left: 24
};

// Reference to current active monitor
//const activeMonitor = reactive(MonitorsService.activeMonitor!);
const parseTime = d3.utcParse("%Y-%m-%dT%H:%M:%S.%LZ");
// Positioning styles
const styles = {
  height: 300 - margin.top - margin.bottom,
  margin,
  width: 0,
};
// SVG chart
let chart: d3.Selection<SVGGElement, unknown, HTMLElement, any>;
// Chart data
let chartData: ChartDataArray;
// Component container element
let container: d3.Selection<d3.BaseType, unknown, HTMLElement, any>;
// Current data fields
let dataFields: Array<ChartDataField> = [];
// Chart legend
let legend: d3.Selection<HTMLDivElement, unknown, HTMLElement, any>;
// D3 data path definitions
let pathDefinition: d3.Line<[number, number]>;
// Function to tell d3 how to read the date
// SVG element
let svg: d3.Selection<SVGSVGElement, unknown, HTMLElement, any>;
// Reference for tooltip
let tooltip: any;
let tooltipLine: d3.Selection<SVGLineElement, unknown, HTMLElement, any>;
let tooltipLinePoints: any;
// Ranges for axes
let x: any = null;
let y: any = null;

watchEffect(async () => {
  chartData = await monitorsService.fetchChartData(monitorsService.activeMonitor!.data.id) || [];
  await d3Service.updateLastActiveLimit(monitorsService.activeMonitor!.data.last_active_limit);
  await loadData();
});

onMounted(() => {
  // Reference to the svg"s container div
  container = d3.select("#chartContainer");

  // Create the SVG element
  //Selection<SVGElement, uknown, HTMLElement, any>
  svg = container.append("svg")
    .attr("width", "100%")
    .attr("height", styles.height + styles.margin.top + styles.margin.bottom);

  // Update positioning styles for "100%" width
  const svgClientRect = svg!.node()!.getBoundingClientRect();
  styles.width = svgClientRect.width - styles.margin.left - styles.margin.right;

  // Set the ranges
  x = d3.scaleTime().range([0, styles.width]);
  y = d3.scaleLinear().range([styles.height, 0]);

  // Create the inititial group that will be our chart
  chart = svg.append("g")
    .attr("transform", `translate(${ styles.margin.left } ${ styles.margin.top })`);

  // Add a group to hold the X Axis
  chart.append("g")
      .attr("class", "xaxis")
      .attr("transform", `translate(0 ${styles.height})`);

  // Add a group to hold the Y Axis
  chart.append("g")
    .attr("class", "yaxis")
    .attr("transform", `translate(${ styles.width }, 0)`);

  // Create path definition, convert data to path
  pathDefinition = d3.line()
    .x(d => x(parseTime((d as any).xData)))
    .y(d => y((d as any).yData));

  // Add text box for legend
  legend = container.append("div")
      .attr("class", "chart-legend")

  // Create tooltip element
  tooltip = container.append("div").attr("class", "chart-tooltip");
  tooltipLine = chart.append("line").attr("class", "chart-tooltip-line");
  tooltipLinePoints = chart.append("g")

  // Add Overlay to watch for events (TipBox)
  svg.append("rect")
    .attr("transform", `translate(${ styles.margin.left } ${ styles.margin.top })`)
    .attr("width", styles.width)
    .attr("height", styles.height)
    .attr("opacity", 0)
    .on("mousemove", e => window.requestAnimationFrame(() => { renderTooltip(e); }))
    .on("mouseout", () => window.requestAnimationFrame(() => { removeTooltip(); }));
});

// This is a generic function to be used both for initialization
//   and for updating the chart. D3's "merge" method is key here.
async function loadData() {
  // create a flat copy of the chart data to find min/max values
  const flatData = chartData.flat();

  // Scale ranges for data, performance assumptions possible
  x.domain(
    d3.extent(flatData, d => parseTime(d.xData))
  );
  y.domain([
    d3.min(flatData, d => Math.floor(d.yData)),
    d3.max(flatData, d => Math.ceil(d.yData))
  ]).nice();

  const toRemove = dataFields.filter(field => !monitorsService.activeMonitor!.dataFields.includes(field))

  for (let i = 0; i <= chartData.length - 1; i++) {
    const data = chartData[i];
    const color = data[0].color;
    const field = data[0].fieldName;
    const gapsId = `chart-gaps-${ field }`;
    const segmentsID = `chart-segments-${ field }`;

    if (toRemove.length) {
      for (let i in toRemove) {
        const field = toRemove[i];
        chart.selectAll(`.chart-gaps-${ field }`).remove();
        chart.selectAll(`.chart-segments-${ field }`).remove();
      }
    }

    const { gaps, segments } = await d3Service.computeSegments(data);

    const gapsLine = chart.selectAll(`.${ gapsId }`)
      .data([gaps]);

    const segmentsLine: any = chart.selectAll(`.${ segmentsID }`)
      .data(segments);

    gapsLine.exit().remove();
    segmentsLine.exit().remove();

    gapsLine.enter()
      .append("path")
      .attr("class", `${ gapsId } gap-line`)
      .attr("d", pathDefinition(gaps))
      .attr("fill", "none");

    segmentsLine.enter()
      .append("path")
      .attr("class", `${segmentsID} segment-line`)
      .merge(segmentsLine)
      .attr("d", pathDefinition)
      .attr("stroke", () => color)
      .attr("fill", "none");
  }

  // Update current data fields
  dataFields = monitorsService.activeMonitor!.dataFields;

  // Add the chart legend
  const legendKeys = legend.selectAll(".legend-key")
    .data(chartData);

  legendKeys.exit().remove();

  const legendKeyValues = legendKeys.enter()
    .append("p")
    .attr("class", "legend-key")

  legendKeyValues.append("span")
    .attr("class", "chart-legend-marker")
    .style("background-color", d => d[0].color);

  legendKeyValues.append("span").text(d => d[0].fieldName)

  legendKeys.merge(legendKeys);

  // Add the X Axis
  chart.selectAll(".xaxis")
      .call(d3.axisBottom(x) as any);

  // Add the Y Axis
  chart.selectAll(".yaxis")
      .call(d3.axisLeft(y).tickSize(styles.width) as any);
}

function renderTooltip(e: any) {
  const pointerCoords = d3.pointer(e, chart.node());
  const xDate = x.invert(pointerCoords[0]);
  const pointerValues = [];

  for (let collection of chartData) {
    const dataPoint = [...collection].find((d, i) => {
        if (new Date(d.xData) <= xDate) {
          return i;
        }
        return;
      });
    pointerValues.push(dataPoint);
  }

  const tooltipLineX = x(parseTime(pointerValues[0]!.xData));
  tooltipLine.classed("active", true)
    .attr("x1", tooltipLineX)
    .attr("x2", tooltipLineX)
    .attr("y1", 0)
    .attr("y2", styles.height);

  const linePoints = tooltipLinePoints.selectAll(".tooltip-line-point")
    .data(pointerValues);

  linePoints.enter()
    .append("circle")
    .attr("class", "tooltip-line-point")
    .merge(linePoints)
    .attr("r", 7)
    .attr("cx", (d: ChartDataPoint) => `${ x(parseTime(d.xData)) }px`)
    .attr("cy", (d: ChartDataPoint) => `${ y(d.yData) }px`)
    .attr("fill", (d: ChartDataPoint) => d.color);

  const lineStats = tooltipLine.node()!
    .getBoundingClientRect();

  const tooltipLegend = tooltip
    .html(`<p class="chart-tooltip-header">${ dateUtil.$prettyPrint(pointerValues[0]!.xData) }</p>`)
    .classed("active", true)
    .style("left", `calc(${ lineStats.x }px + 2em)`)
    .style("top", `calc(${ e.layerY }px + 3.5em)`)
    .append("div")
    .attr("class", "chart-tooltip-legend");

  const tooltipLegendItems = tooltipLegend.selectAll(".chart-legend-item")
    .data(pointerValues)

  const legendItemsDetails = tooltipLegendItems.enter()
    .append("p")
    .attr("class", "chart-tooltip-legend-item")
    .merge(tooltipLegend);

  legendItemsDetails.append("span")
    .attr("class", "chart-legend-marker")
    .style("background-color", (d: ChartDataPoint) => d.color);

  legendItemsDetails.append("span")
    .merge(tooltipLegend)
    .text((d: ChartDataPoint) => `${ d.fieldName }: `)
    .append("b")
    .text((d: ChartDataPoint) => `${ Math.round(d.yData) }`);
}

function removeTooltip() {
  if (tooltip.node()!.classList.contains("active")) {
    tooltip.classed("active", false)
  }
  if (tooltipLine.node()!.classList.contains("active")) {
    tooltipLine.classed("active", false)
  }
  tooltipLinePoints.selectAll(".tooltip-line-point").remove();
}
</script>

<template>
  <div id="chartContainer" class="chart-container"></div>
</template>

