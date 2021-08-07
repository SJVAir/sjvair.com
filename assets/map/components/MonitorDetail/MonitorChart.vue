<template>
  <div id="chartContainer" class="chart-container"></div>
</template>

<script>
import * as d3 from "d3";
import dateUtil from "../../utils/date";
import monitorsService from "../../services/Monitors.service";

const margin = {
  top: 24,
  right: 24,
  bottom: 56,
  left: 24
};

/**
 * Helper function to compute the contiguous segments of the data
 *
 * Derived from https://github.com/pbeshai/d3-line-chunked/blob/master/src/lineChunked.js
 *
 * @param {Array} lineData the line data
 * @param {Function} defined function that takes a data point and returns true if
 *    it is defined, false otherwise
 * @param {Function} isNext function that takes the previous data point and the
 *    current one and returns true if the current point is the expected one to
 *    follow the previous, false otherwise.
 * @return {Array} An array of segments (subarrays) of the line data
 */
function computeSegments(lineData, defined, isNext) {
  defined = defined || function () { return true; };
  isNext = isNext || function () { return true; };
  let startNewSegment = true;

  // split into segments of continuous data
  let segments = lineData.reduce(function (segments, d) {
    // skip if this point has no data
    if (!defined(d)) {
      startNewSegment = true;
      return segments;
    }

    // if we are starting a new segment, start it with this point
    if (startNewSegment) {
      segments.push([d]);
      startNewSegment = false;

    // otherwise see if we are adding to the last segment
    } else {
      const lastSegment = segments[segments.length - 1];
      const lastDatum = lastSegment[lastSegment.length - 1];
      // if we expect this point to come next, add it to the segment
      if (isNext(lastDatum, d)) {
        lastSegment.push(d);

      // otherwise create a new segment
      } else {
        segments.push([d]);
      }
    }

    return segments;
  }, []);

  return segments;
}

// Calculate if there should be a line between 2 given points
function lineDefined(dataPoint) {
  if (!lineDefined.prevDataPoint) {
    lineDefined.prevDataPoint = dataPoint;
    return true;
  }

  let deltaRaw = dateUtil(dataPoint.xData).diff(dateUtil(lineDefined.prevDataPoint.xData));
  const deltaAsMin = Math.ceil(deltaRaw / (1000 * 60));

  lineDefined.prevDataPoint = dataPoint;
  return deltaAsMin < lineDefined.maxDelta;
}
lineDefined.maxDelta = 5;

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
      // D3 data path definitions
      pathDefinition: null,
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

    // Create path definition, convert data to path
    this.pathDefinition = d3.line()
      .x(d => this.x(this.parseTime(d.xData)))
      .y(d => this.y(d.yData));

    // Add text box for legend
    this.legend = this.container.append("div")
        .attr("class", "chart-legend")

    // Create tooltip element
    this.tooltip = this.container.append("div").attr("class", "chart-tooltip");
    this.tooltipLine = this.chart.append("line").attr("class", "chart-tooltip-line");
    this.tooltipLinePoints = this.chart.append("g")

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


      for (let i in this.activeMonitor.chartData) {
        const data = this.activeMonitor.chartData[i];
        const color = this.activeMonitor.chartData[i].color;
        const gapsId = `chart-gaps-${ i }`;
        const segmentsID = `chart-segments-${ i }`;

        const segments = computeSegments(data, lineDefined)
        const gaps = [data.filter(lineDefined)];

        const gapsLine = this.chart.selectAll(`.${ gapsId }`)
          .data(gaps);

        const segmentsLine = this.chart.selectAll(`.${ segmentsID }`)
          .data(segments);

        gapsLine.exit().remove();
        segmentsLine.exit().remove();

        gapsLine.enter()
          .append("path")
          .attr("class", segmentsID)
          .attr("d", this.pathDefinition(gaps.pop()))
          .attr("fill", "none");

        segmentsLine.enter()
          .append("path")
          .attr("class", segmentsID)
          .merge(segmentsLine)
          .attr("d", this.pathDefinition)
          .attr("stroke", () => color)
          .attr("fill", "none");
      }

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

      const tooltipLineX = this.x(this.parseTime(pointerValues[0].xData));
      this.tooltipLine.classed("active", true)
        .attr("x1", tooltipLineX)
        .attr("x2", tooltipLineX)
        .attr("y1", 0)
        .attr("y2", this.styles.height);

      const tooltipLinePoints = this.tooltipLinePoints.selectAll(".tooltip-line-point")
        .data(pointerValues);

      tooltipLinePoints.exit().remove();

      tooltipLinePoints.enter()
        .append("circle")
        .attr("class", "tooltip-line-point")
        .merge(tooltipLinePoints)
        .attr("r", 7)
        .attr("cx", d => `${ this.x(this.parseTime(d.xData)) }px`)
        .attr("cy", d => `${ this.y(d.yData) }px`)
        .attr("fill", d => d.color);

      const lineStats = this.tooltipLine.node()
        .getBoundingClientRect();

      const tooltip = this.tooltip
        .html(`<p class="chart-tooltip-header">${ this.$date.$prettyPrint(pointerValues[0].xData) }</p>`)
        .classed("active", true)
        .style("left", `calc(${ lineStats.x }px + 2em)`)
        .style("top", `calc(${ e.layerY }px + 3.5em)`)
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
      if (this.tooltip.node().classList.contains("active")) {
        this.tooltip.classed("active", false)
      }
      if (this.tooltipLine.node().classList.contains("active")) {
        this.tooltipLine.classed("active", false)
      }
      this.tooltipLinePoints.selectAll(".tooltip-line-point").remove();
    }
  }
}
</script>
