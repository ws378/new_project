#!/usr/bin/env bash
set +e

source /opt/ros/humble/setup.bash
export DISPLAY=:1
export XAUTHORITY=/run/user/1003/gdm/Xauthority

echo "=== 启动 Nav2 覆盖路径仿真 ==="
date

MAP_YAML="/home/wangshuang/my_new/examples/maptools_projects/map.yaml"
COV_YAML="/home/wangshuang/my_new/examples/maptools_projects/maptools_projects/coverage_path_master.yaml"
RVIZ_CFG="/home/wangshuang/my_new/ros_nodes/coverage_sim.rviz"
TB3_URDF="/home/wangshuang/my_new/ros_nodes/robot.urdf"
NAV2_PARAMS="/home/wangshuang/my_new/ros_nodes/nav2_all_params.yaml"

# 1) map_server
ros2 run nav2_map_server map_server --ros-args -p yaml_filename:="$MAP_YAML" -r __node:=map_server &
sleep 2
timeout 5 ros2 service call /map_server/change_state lifecycle_msgs/srv/ChangeState '{transition: {id: 1}}' 2>/dev/null || true
sleep 1
timeout 5 ros2 service call /map_server/change_state lifecycle_msgs/srv/ChangeState '{transition: {id: 3}}' 2>/dev/null || true
echo "  [OK] map_server"

# 2) static TF map→odom
ros2 run tf2_ros static_transform_publisher 0 0 0 0 0 0 map odom &
sleep 1
echo "  [OK] static_tf"

# 3) coverage path visualization
python3 /home/wangshuang/my_new/ros_nodes/coverage_path_rviz.py --yaml "$COV_YAML" &
sleep 1
echo "  [OK] cov_viz"

# 4) diff drive simulator (从 coverage yaml 自动获取起始位置)
START_POSE=$(source /opt/ros/humble/setup.bash && python3 -c "
import yaml, math
with open('$COV_YAML') as f:
    data = yaml.safe_load(f)
p0 = data['paths'][0]['poses'][0]
p1 = data['paths'][0]['poses'][1]
theta = math.atan2(p1['y'] - p0['y'], p1['x'] - p0['x'])
print(f'{p0[\"x\"]} {p0[\"y\"]} {theta}')
")
read -r INIT_X INIT_Y INIT_THETA <<< "$START_POSE"
echo "  [位置] 起点: ($INIT_X, $INIT_Y, $INIT_THETA)"
python3 /home/wangshuang/my_new/ros_nodes/diff_drive_sim.py \
    --ros-args -p initial_x:=$INIT_X -p initial_y:=$INIT_Y -p initial_theta:=$INIT_THETA &
sleep 1
echo "  [OK] diff_drive"

# 5) robot_state_publisher
ROBOT_DESC=$(cat "$TB3_URDF")
ros2 run robot_state_publisher robot_state_publisher --ros-args -p robot_description:="$ROBOT_DESC" &
sleep 1
echo "  [OK] rsp"

# 6) simulated laser
python3 /home/wangshuang/my_new/ros_nodes/simulated_laser.py --ros-args -p map_yaml:="$MAP_YAML" &
sleep 2
echo "  [OK] simulated_laser"

# 7) Nav2 controller_server (DWB + local costmap)
ros2 run nav2_controller controller_server --ros-args --params-file "$NAV2_PARAMS" &
sleep 5
echo "  [OK] controller_server"

# 8) lifecycle activation
timeout 5 ros2 service call /controller_server/change_state lifecycle_msgs/srv/ChangeState '{transition: {id: 1}}' 2>/dev/null || true
sleep 2
timeout 5 ros2 service call /controller_server/change_state lifecycle_msgs/srv/ChangeState '{transition: {id: 3}}' 2>/dev/null || true
sleep 1
echo "  [OK] activated"

# 9) rviz2
rviz2 -d "$RVIZ_CFG" &
sleep 3
echo "  [OK] rviz2"

echo ""
echo "================== READY =================="
echo "启动路径跟踪:"
echo "  python3 /home/wangshuang/my_new/ros_nodes/coverage_path_commander.py --yaml $COV_YAML"
echo "------------------------------------------"
echo "停止仿真:"
echo "  pkill -9 -f 'map_server|controller_server|diff_drive|simulated_laser|rviz2|coverage_path|robot_state_publisher|static_transform'"
echo "=========================================="

sleep 99999