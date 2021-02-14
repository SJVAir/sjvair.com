import * as d3 from "d3";
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";
import timezone from "dayjs/plugin/timezone";

dayjs.extend(utc);
dayjs.extend(timezone);

class ChartController {
  constructor() {
    this.colors = ["#00ccff", "#006699", "#000033"],
    this.container = null;
    this.dataFields = null;
    this.svg = null;
    this.margin = {top: 20, right: 20, bottom: 30, left: 50};
    this.width = 960 - this.margin.left - this.margin.right;
    this.height = 500 - this.margin.top - this.margin.bottom;

    // Function to tell d3 how to read the date
    this.parseTime = d3.timeParse("%Y-%m-%dT%H:%M:%S.%LZ");

    // Set the ranges
    this.x = d3.scaleTime().range([0, this.width]);
    this.y = d3.scaleLinear().range([this.height, 0]);

    // Store line functions
    this.lineConfigs = [];
  }

  init(dataFields) {
    // Reference to the svg"s container div
    this.container = d3.select("#chartContainer");

    // Reference to data fields in monitor we will grab
    this.dataFields = dataFields;

    // Define functions that will generate the lines for each field
    for (let i in this.dataFields) {
      this.lineConfigs.push({
        color: this.colors[i],
        field: this.dataFields[i],
        line: d3.line()
          .x(d => this.x(this.parseTime(d.timestamp)))
          .y(d => this.y(d[this.dataFields[i]]))
      });
    }

    // Append the svg object to our container
    this.svg = this.container.append("svg")
      .attr("width", this.width + this.margin.left + this.margin.right)
      .attr("height", this.height + this.margin.top + this.margin.bottom)
      // Appends a "group" element to "svg"
      .append("g")
      // Moves the "group" element to the top left margin
      .attr("transform", `translate(${ this.margin.left } ${ this.margin.top })`);

    // Add the X Axis
    this.svg.append("g")
        .attr("class", "xaxis")
        .attr("transform", `translate(0 ${this.height})`)

    // Add the Y Axis
    this.svg.append("g")
      .attr("class", "yaxis")
  }

  loadDataset(data) {
    data = data.map(d => {
      // Time parsing should happen elsewhere, make it happen before this goes live
      d.timestamp = dayjs.utc(d.timestamp).tz("America/Los_Angeles").toISOString();
      for (let f of this.dataFields) {
        d[f] = parseFloat(d[f], 10);
      }
      return d;
    });

    // Scale the range of the data, assumptions could be
    // made to speed things up
    this.x.domain(d3.extent(data, d => this.parseTime(d.timestamp)));
    this.y.domain([
      0,
      d3.max(data, d => Math.max(...this.dataFields.map(f => d[f])))
    ]);

    // Add the valueline paths.
    for (let cfg of this.lineConfigs) {
      const line = this.svg.selectAll(`.${cfg.field}`)
        .data([data]);

      line.enter()
        .append("path")
        .attr("class", cfg.field)
        .merge(line)
        .transition()
        .duration(2000)
        .attr("d", cfg.line)
        .attr("fill", "none")
        .attr("stroke", cfg.color)
        .attr("stroke-width", 1)
        .attr("stroke-linejoin", "round")
        .attr("stroke-linecap", "round")
    }

    // Add the X Axis
    this.svg.selectAll(".xaxis")
        .transition()
        .duration(2000)
        .call(d3.axisBottom(this.x));

    // Add the Y Axis
    this.svg.selectAll(".yaxis")
        .call(d3.axisLeft(this.y));
  }
}

export default new ChartController();
