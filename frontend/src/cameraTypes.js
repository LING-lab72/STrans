export const CAMERA_TYPE_OPTIONS = [
  { value: "custom", label: "自定义" },
  { value: "phone", label: "手机" },
  { value: "usb", label: "USB 摄像头" },
  { value: "sandtable", label: "沙盘 RTSP" },
];

export function monitorCameraOptions(cameras) {
  return Array.isArray(cameras) ? cameras : [];
}
