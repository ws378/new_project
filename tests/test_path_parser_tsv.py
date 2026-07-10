from pathlib import Path

from maptools.models.coverage_path import CoveragePathNode, PathParser


def test_load_tsv_populates_output_nodes(tmp_path: Path):
    path_file = tmp_path / "path.tsv"
    path_file.write_text(
        "ID\tRoom\tSegment\tX(m)\tY(m)\tYaw(rad)\tU(px)\tV(px)\tAcc_Dist\tRoom_Dist\tSeg_Dist\n"
        "0\t1\t0\t1.000000\t2.000000\t0.100000\t10\t20\t0.000\t0.000\t0.000\n"
        "1\t1\t0\t1.500000\t2.000000\t0.200000\t15\t20\t0.500\t0.500\t0.500\n",
        encoding="utf-8",
    )

    out_nodes = []
    PathParser.load_tsv(str(path_file), out_nodes, map_meta=None)

    assert len(out_nodes) == 2
    assert out_nodes[0].room == 1
    assert out_nodes[1].x == 1.5


def test_save_tsv_writes_header_and_data(tmp_path: Path):
    output = tmp_path / "saved.tsv"
    nodes = [
        CoveragePathNode(
            id=0,
            room=2,
            segment=3,
            x=1.0,
            y=2.0,
            yaw=0.0,
            u=10.0,
            v=20.0,
            acc_dist=0.0,
            room_dist=0.0,
            seg_dist=0.0,
        )
    ]

    PathParser.save_tsv(
        str(output),
        nodes,
        map_meta=None,
        recompute_dist=False,
        recompute_yaw=False,
    )

    text = output.read_text(encoding="utf-8")
    assert "ID\tRoom\tSegment\tX(m)\tY(m)\tYaw(rad)\tU(px)\tV(px)\tAcc_Dist\tRoom_Dist\tSeg_Dist" in text
    assert "0\t2\t3\t1.000000\t2.000000\t0.000000\t10\t20\t0.000\t0.000\t0.000" in text
