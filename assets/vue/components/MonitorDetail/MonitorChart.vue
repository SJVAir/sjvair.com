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
let dataFields: Array<ChartDataField>;
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
  await loadData();
});

onMounted(() => {
  // Reference to the svg"s container div
  container = d3.select("#chartContainer");
  console.log(container)

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
    const dataPoint = [...collection].reverse().find((d, i) => {
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

  tooltipLinePoints = tooltipLinePoints.selectAll(".tooltip-line-point")
    .data(pointerValues);

  tooltipLinePoints.exit().remove();

  tooltipLinePoints.enter()
    .append("circle")
    .attr("class", "tooltip-line-point")
    .merge(tooltipLinePoints as any)
    .attr("r", 7)
    .attr("cx", (d: ChartDataPoint) => `${ x(parseTime(d.xData)) }px`)
    .attr("cy", (d: ChartDataPoint) => `${ y(d.yData) }px`)
    .attr("fill", (d: ChartDataPoint) => d.color);

  const lineStats = tooltipLine.node()!
    .getBoundingClientRect();

  tooltip = tooltip
    .html(`<p class="chart-tooltip-header">${ dateUtil.$prettyPrint(pointerValues[0]!.xData) }</p>`)
    .classed("active", true)
    .style("left", `calc(${ lineStats.x }px + 2em)`)
    .style("top", `calc(${ e.layerY }px + 3.5em)`)
    .selectAll()
    .data(pointerValues).enter()
    .append("div")
    .attr("class", "chart-tooltip-value");

  tooltip.append("span").attr("class", "chart-legend-marker")
    .style("background-color", (d: ChartDataPoint) => d.color);

  tooltip.append("span")
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
//export default {
//  name: "monitor-chart",
//
//  props: [ "chartData" ],
//
//  data() {
//    return {
//      // Current data fields
//      dataFields: [],
//      ctx: monitorsService,
//      // SVG chart
//      chart: null,
//      // Component container element
//      container: null,
//      // Chart legend
//      legend: null,
//      // D3 data path definitions
//      pathDefinition: null,
//      // Function to tell d3 how to read the date
//      parseTime: d3.utcParse("%Y-%m-%dT%H:%M:%S.%LZ"),
//      // Positioning styles
//      styles: {
//          height: 300 - margin.top - margin.bottom,
//          margin,
//          width: null,
//        },
//      // SVG element
//      svg: null,
//      // Overlay to watch for events
//      tipbox: null,
//      // Reference for tooltip
//      tooltip: null,
//      // Ranges for axes
//      x: null,
//      y: null,
//    };
//  },
//
//  computed: {
//    activeMonitor() { return this.ctx.activeMonitor; }
//  },
//
//  mounted() {
//    // Reference to the svg"s container div
//    this.container = d3.select("#chartContainer");
//
//    // Create the SVG element
//    this.svg = this.container.append("svg")
//      .attr("width", "100%")
//      .attr("height", this.styles.height + this.styles.margin.top + this.styles.margin.bottom);
//
//    // Update positioning styles for "100%" width
//    const svgClientRect = this.svg.node().getBoundingClientRect();
//    this.styles.width = svgClientRect.width - this.styles.margin.left - this.styles.margin.right;
//
//    // Set the ranges
//    this.x = d3.scaleTime().range([0, this.styles.width]);
//    this.y = d3.scaleLinear().range([this.styles.height, 0]);
//
//    // Create the inititial group that will be our chart
//    this.chart = this.svg.append("g")
//      .attr("transform", `translate(${ this.styles.margin.left } ${ this.styles.margin.top })`);
//
//    // Add a group to hold the X Axis
//    this.chart.append("g")
//        .attr("class", "xaxis")
//        .attr("transform", `translate(0 ${this.styles.height})`);
//
//    // Add a group to hold the Y Axis
//    this.chart.append("g")
//      .attr("class", "yaxis")
//      .attr("transform", `translate(${ this.styles.width }, 0)`);
//
//    // Create path definition, convert data to path
//    this.pathDefinition = d3.line()
//      .x(d => this.x(this.parseTime(d.xData)))
//      .y(d => this.y(d.yData));
//
//    // Add text box for legend
//    this.legend = this.container.append("div")
//        .attr("class", "chart-legend")
//
//    // Create tooltip element
//    this.tooltip = this.container.append("div").attr("class", "chart-tooltip");
//    this.tooltipLine = this.chart.append("line").attr("class", "chart-tooltip-line");
//    this.tooltipLinePoints = this.chart.append("g")
//
//    // Add Overlay to watch for events
//    this.tipbox = this.svg.append("rect")
//      .attr("transform", `translate(${ this.styles.margin.left } ${ this.styles.margin.top })`)
//      .attr("width", this.styles.width)
//      .attr("height", this.styles.height)
//      .attr("opacity", 0)
//      .on("mousemove", e => window.requestAnimationFrame(() => { this.renderTooltip(e); }))
//      .on("mouseout", e => window.requestAnimationFrame(() => { this.removeTooltip(e); }));
//  },
//
//  watch: {
//    "ctx.activeMonitor.chartData": async function() {
//      if (this.ctx.activeMonitor.chartData.length) {
//        await bgtc.run("updateLastActiveLimit", this.ctx.activeMonitor.last_active_limit);
//        await this.loadData();
//      }
//    }
//  },
//
//  methods: {
//    // This is a generic function to be used both for initialization
//    //   and for updating the chart. D3's "merge" method is key here.
//    async loadData() {
//      // create a flat copy of the chart data to find min/max values
//      const flatData = this.activeMonitor.chartData.flat();
//
//      // Scale ranges for data, performance assumptions possible
//      this.x.domain(
//        d3.extent(flatData, d => this.parseTime(d.xData))
//      );
//      this.y.domain([
//        d3.min(flatData, d => parseInt(Math.floor(d.yData), 10)),
//        d3.max(flatData, d => parseInt(Math.ceil(d.yData), 10))
//      ]).nice();
//
//      const toRemove = this.dataFields.filter(field => !this.activeMonitor.dataFields.includes(field))
//
//      for (let i in this.activeMonitor.chartData) {
//        const data = this.activeMonitor.chartData[i];
//        const color = data.color;
//        const field = data.fieldName;
//        const gapsId = `chart-gaps-${ field }`;
//        const segmentsID = `chart-segments-${ field }`;
//
//        if (toRemove.length) {
//          for (let i in toRemove) {
//            const field = toRemove[i];
//            this.chart.selectAll(`.chart-gaps-${ field }`).remove();
//            this.chart.selectAll(`.chart-segments-${ field }`).remove();
//          }
//        }
//
//        const { gaps, segments } = await bgtc.run("computeSegments", data);
//
//        const gapsLine = this.chart.selectAll(`.${ gapsId }`)
//          .data([gaps]);
//
//        const segmentsLine = this.chart.selectAll(`.${ segmentsID }`)
//          .data(segments);
//
//        gapsLine.exit().remove();
//        segmentsLine.exit().remove();
//
//        gapsLine.enter()
//          .append("path")
//          .attr("class", `${ gapsId } gap-line`)
//          .attr("d", this.pathDefinition(gaps))
//          .attr("fill", "none");
//
//        segmentsLine.enter()
//          .append("path")
//          .attr("class", `${segmentsID} segment-line`)
//          .merge(segmentsLine)
//          .attr("d", this.pathDefinition)
//          .attr("stroke", () => color)
//          .attr("fill", "none");
//      }
//
//      // Update current data fields
//      this.dataFields = this.activeMonitor.dataFields;
//
//      // Add the chart legend
//      const legendKeys = this.legend.selectAll(".legend-key")
//        .data(this.activeMonitor.chartData);
//
//      legendKeys.exit().remove();
//
//      const legendKeyValues = legendKeys.enter()
//        .append("p")
//        .attr("class", "legend-key")
//
//      legendKeyValues.append("span")
//        .attr("class", "chart-legend-marker")
//        .style("background-color", d => d.color);
//
//      legendKeyValues.append("span").text(d => d.fieldName)
//
//      legendKeys.merge(legendKeys);
//
//      // Add the X Axis
//      this.chart.selectAll(".xaxis")
//          .call(d3.axisBottom(this.x));
//
//      // Add the Y Axis
//      this.chart.selectAll(".yaxis")
//          .call(d3.axisLeft(this.y).tickSize(this.styles.width));
//    },
//
//    renderTooltip(e) {
//      const pointerCoords = d3.pointer(e, this.chart.node());
//      const xDate = this.x.invert(pointerCoords[0]);
//      const pointerValues = [];
//
//      for (let collection of this.activeMonitor.chartData) {
//        const dataPoint = [...collection].reverse().find((d, i) => {
//            if (new Date(d.xData) <= xDate) {
//              return i;
//            }
//          });
//        pointerValues.push(dataPoint);
//      }
//
//      const tooltipLineX = this.x(this.parseTime(pointerValues[0].xData));
//      this.tooltipLine.classed("active", true)
//        .attr("x1", tooltipLineX)
//        .attr("x2", tooltipLineX)
//        .attr("y1", 0)
//        .attr("y2", this.styles.height);
//
//      const tooltipLinePoints = this.tooltipLinePoints.selectAll(".tooltip-line-point")
//        .data(pointerValues);
//
//      tooltipLinePoints.exit().remove();
//
//      tooltipLinePoints.enter()
//        .append("circle")
//        .attr("class", "tooltip-line-point")
//        .merge(tooltipLinePoints)
//        .attr("r", 7)
//        .attr("cx", d => `${ this.x(this.parseTime(d.xData)) }px`)
//        .attr("cy", d => `${ this.y(d.yData) }px`)
//        .attr("fill", d => d.color);
//
//      const lineStats = this.tooltipLine.node()
//        .getBoundingClientRect();
//
//      const tooltip = this.tooltip
//        .html(`<p class="chart-tooltip-header">${ this.$date.$prettyPrint(pointerValues[0].xData) }</p>`)
//        .classed("active", true)
//        .style("left", `calc(${ lineStats.x }px + 2em)`)
//        .style("top", `calc(${ e.layerY }px + 3.5em)`)
//        .selectAll()
//        .data(pointerValues).enter()
//        .append("div")
//        .attr("class", "chart-tooltip-value");
//
//      tooltip.append("span").attr("class", "chart-legend-marker")
//        .style("background-color", d => d.color);
//
//      tooltip.append("span")
//        .text(d => `${ d.fieldName }: `)
//        .append("b")
//        .text(d => `${ Math.round(d.yData) }`);
//    },
//
//    removeTooltip() {
//      if (this.tooltip.node().classList.contains("active")) {
//        this.tooltip.classed("active", false)
//      }
//      if (this.tooltipLine.node().classList.contains("active")) {
//        this.tooltipLine.classed("active", false)
//      }
//      this.tooltipLinePoints.selectAll(".tooltip-line-point").remove();
//    }
//  }
//}
</script>
<template>
  <div id="chartContainer" class="chart-container"></div>
</template>

