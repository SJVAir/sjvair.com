import * as L from "leaflet";

import type { ILeafletTileLayer } from "../types";

const mapSettings = {
  // Initial location: Fresno, CA
  center: new L.LatLng( 36.746841, -119.772591 ),
  zoom: 8
};

export class InteractiveMap {
  private baseLayer!: L.TileLayer;
  private map: L.Map;
  private markersGroup = new L.FeatureGroup();
  private tileOverlays: Map<string, L.TileLayer> = new Map();

  constructor(id: string) {
    this.map = L.map(id, mapSettings);

    this.markersGroup.addTo(this.map);

    this.map.createPane("purpleAir").style.zIndex = "601";
    this.map.createPane("airNow").style.zIndex = "602";
    this.map.createPane("sjvAirPurpleAir").style.zIndex = "603";
    this.map.createPane("sjvAirBam").style.zIndex = "604";
  }

  addMarker(marker: L.Marker) {
    this.markersGroup.addLayer(marker);
  }

  addOverlay(overlay: ILeafletTileLayer) {
    const layer = L.tileLayer(overlay.urlTemplate, overlay.options).addTo(this.map);
    this.tileOverlays.set(overlay.label, layer);
  }

  fitBounds() {
    this.map.fitBounds(this.markersGroup.getBounds());
  }

  hideMarker(marker: L.Marker) {
    this.markersGroup.removeLayer(marker);
  }

  invalidateSize() {
    this.map.invalidateSize();
  }

  recenter(coordinates: L.LatLng) {
    // Don't adjust the zoom if we're already zoomed in greater than 10
    const zoom = Math.max(this.map.getZoom(), 10);
    this.map.setView(coordinates, zoom, { animate: true });
  }

  removeMarker(marker: L.Marker) {
    this.markersGroup.removeLayer(marker.remove());
  }

  removeOverlay(label: string) {
    if (this.tileOverlays.has(label)) {
      this.tileOverlays.get(label)!.remove();
      this.tileOverlays.delete(label);
    }
  }

  setbaseLayer(layer: ILeafletTileLayer) {
    if (this.baseLayer) {
      this.baseLayer.remove();
    }
    this.baseLayer = L.tileLayer(layer.urlTemplate, layer.options).addTo(this.map);
  }

  showMarker(marker: L.Marker) {
    this.markersGroup.removeLayer(marker);
  }
}
