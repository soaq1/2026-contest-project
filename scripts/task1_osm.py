# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import osmnx as ox

G = ox.graph_from_place("Daejeon, South Korea", network_type="drive")
ox.save_graphml(G, "output/daejeon_drive.graphml")

n_nodes = len(G.nodes)
n_edges = len(G.edges)
print(f"nodes={n_nodes}, edges={n_edges}")
if n_nodes < 100:
    print("WARNING: node count under 100 - graph looks abnormal")
else:
    print("OK: graph size looks normal")
