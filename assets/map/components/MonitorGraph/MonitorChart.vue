<template>
  <div id="chartContainer" class="chart-container"></div>
</template>

<script>
import * as d3 from "d3";
import monitorsService from "../../services/Monitors.service";

const margin = {
  top: 24,
  right: 24,
  bottom: 56,
  left: 24
};

export default {
  name: "monitor-chart",

  props: [ "chartData" ],

  data() {
    return {
      ctx: monitorsService,
      // SVG chart
      chart: null,
      // Colors for datasets
      colors: ["#00ccff", "#006699", "#000033"],
      // Component container element
      container: null,
      // Chart legend
      legend: null,
      // Function to tell d3 how to read the date
      parseTime: d3.utcParse("%Y-%m-%dT%H:%M:%S.%LZ"),
      // Positioning styles
      styles: {
          height: 300 - margin.top - margin.bottom,
          margin,
          width: null,
        },
      // SVG element
      svg: null,
      // Overlay to watch for events
      tipbox: null,
      // Reference for tooltip
      tooltip: null,
      // Ranges for axes
      x: null,
      y: null,
    };
  },

  computed: {
    activeMonitor() { return this.ctx.activeMonitor; }
  },

  mounted() {
    // Reference to the svg"s container div
    this.container = d3.select("#chartContainer");

    // Create the SVG element
    this.svg = this.container.append("svg")
      .attr("width", "100%")
      .attr("height", this.styles.height + this.styles.margin.top + this.styles.margin.bottom);

    // Update positioning styles for "100%" width
    const svgClientRect = this.svg.node().getBoundingClientRect();
    this.styles.width = svgClientRect.width - this.styles.margin.left - this.styles.margin.right;

    // Set the ranges
    this.x = d3.scaleTime().range([0, this.styles.width]);
    this.y = d3.scaleLinear().range([this.styles.height, 0]);

    // Create the inititial group that will be our chart
    this.chart = this.svg.append("g")
      .attr("transform", `translate(${ this.styles.margin.left } ${ this.styles.margin.top })`);

    // Add a group to hold the X Axis
    this.chart.append("g")
        .attr("class", "xaxis")
        .attr("transform", `translate(0 ${this.styles.height})`);

    // Add a group to hold the Y Axis
    this.chart.append("g")
      .attr("class", "yaxis")
      .attr("transform", `translate(${ this.styles.width }, 0)`);

    // Add text box for legend
    this.legend = this.container.append("div")
        .attr("class", "chart-legend")

    // Create tooltip element
    this.tooltip = this.container.append("div").attr("class", "chart-tooltip");
    this.tooltipLine = this.chart.append("line").attr("class", "chart-tooltip-line");

    // Add Overlay to watch for events
    this.tipbox = this.svg.append("rect")
      .attr("transform", `translate(${ this.styles.margin.left } ${ this.styles.margin.top })`)
      .attr("width", this.styles.width)
      .attr("height", this.styles.height)
      .attr("opacity", 0)
      .on("mousemove", e => window.requestAnimationFrame(() => { this.renderTooltip(e); }))
      .on("mouseout", e => window.requestAnimationFrame(() => { this.removeTooltip(e); }));
  },

  watch: {
    "ctx.activeMonitor.chartData": function() {
      this.loadData();
    }
  },

  methods: {
    // This is a generic function to be used both for initialization
    //   and for updating the chart. D3's "merge" method is key here.
    loadData() {
      // create a flat copy of the chart data to find min/max values
      const flatData = this.activeMonitor.chartData.flat();
      // Scale ranges for data, performance assumptions possible
      this.x.domain(
        d3.extent(flatData, d => this.parseTime(d.xData))
      );
      this.y.domain([
        d3.min(flatData, d => parseInt(Math.floor(d.yData), 10)),
        d3.max(flatData, d => parseInt(Math.ceil(d.yData), 10))
      ]).nice();

      // Add the line definitions to the chart
      const lines = this.chart.selectAll(".chart-line")
        .data(this.activeMonitor.chartData);

      lines.exit().remove();

      lines.enter()
        .append("path")
        .attr("class", "chart-line")
        .merge(lines)
        .attr("d", d3.line().x(d => this.x(this.parseTime(d.xData))).y(d => this.y(d.yData)))
        .attr("stroke", d => d.color)

      // Add the chart legend
      const legendKeys = this.legend.selectAll(".legend-key")
        .data(this.activeMonitor.chartData);

      legendKeys.exit().remove();

      const legendKeyValues = legendKeys.enter()
        .append("p")
        .attr("class", "legend-key")

      legendKeyValues.append("span")
        .attr("class", "chart-legend-marker")
        .style("background-color", d => d.color);

      legendKeyValues.append("span").text(d => d.fieldName)

      legendKeys.merge(legendKeys);

      // Add the X Axis
      this.chart.selectAll(".xaxis")
          .call(d3.axisBottom(this.x));

      // Add the Y Axis
      this.chart.selectAll(".yaxis")
          .call(d3.axisLeft(this.y).tickSize(this.styles.width));
    },

    renderTooltip(e) {
      const pointerCoords = d3.pointer(e, this.chart.node());
      const xDate = this.x.invert(pointerCoords[0]);
      const pointerValues = [];

      for (let collection of this.activeMonitor.chartData) {
        const dataPoint = [...collection].reverse().find((d, i) => {
            if (new Date(d.xData) <= xDate) {
              return i;
            }
          });
        pointerValues.push(dataPoint);
      }

      this.tooltipLine.classed("active", true)
        .attr("x1", pointerCoords[0])
        .attr("x2", pointerCoords[0])
        .attr("y1", 0)
        .attr("y2", this.styles.height);

      const lineEl = this.tooltipLine.node();
      const lineStats = lineEl.getBoundingClientRect();

      const tooltip = this.tooltip
        .html(`<p class="chart-tooltip-header">${ xDate }</p>`)
        .classed("active", true)
        .style("left", `${ lineStats.x }px`)
        .style("top", `${ e.layerY }px`)
        .selectAll()
        .data(pointerValues).enter()
        .append("div")
        .attr("class", "chart-tooltip-value");

      tooltip.append("span").attr("class", "chart-legend-marker")
        .style("background-color", d => d.color);

      tooltip.append("span")
        .text(d => `${ d.fieldName }: `)
        .append("b")
        .text(d => `${ Math.round(d.yData) }`);
    },

    removeTooltip() {
      if (this.tooltip) {
        this.tooltip.classed("active", false)
        //.style("display", "none");
      }
      if (this.tooltipLine) {
        this.tooltipLine.classed("active", false)
        //.attr("stroke", "none");
      }
    }
  }
}
</script>
