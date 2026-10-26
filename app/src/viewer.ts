// Three.js 3D 视图：模型预览、表面压力云图、流线、切片
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { OBJLoader } from "three/examples/jsm/loaders/OBJLoader.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

export interface Viewer {
  dispose(): void;
  clearResult(): void;
  showModelObject(obj: THREE.Object3D): void;
  showSurfaceGlb(buffer: ArrayBuffer): Promise<void>;
  showStreamlines(data: { lines: { points: number[][]; speed: number[] }[] }): void;
  showSlice(data: {
    points: number[][];
    faces: number[][];
    cp: number[];
    vel_mag: number[];
  }): void;
  frameAll(): void;
}

export function createViewer(container: HTMLElement): Viewer {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x1a1d24);

  const camera = new THREE.PerspectiveCamera(
    50,
    container.clientWidth / container.clientHeight,
    0.1,
    2000
  );
  camera.position.set(12, 5, 12);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.setPixelRatio(window.devicePixelRatio);
  container.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;

  scene.add(new THREE.AmbientLight(0xffffff, 0.6));
  const dir = new THREE.DirectionalLight(0xffffff, 1.2);
  dir.position.set(10, 20, 10);
  scene.add(dir);

  // 地面参考网格
  const grid = new THREE.GridHelper(40, 40, 0x3a4050, 0x262a33);
  grid.name = "groundGrid";
  scene.add(grid);

  const modelGroup = new THREE.Group();
  const resultGroup = new THREE.Group();
  scene.add(modelGroup, resultGroup);

  let raf = 0;
  const animate = () => {
    raf = requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  };
  animate();

  const onResize = () => {
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(container.clientWidth, container.clientHeight);
  };
  window.addEventListener("resize", onResize);

  const frameAll = () => {
    const box = new THREE.Box3().setFromObject(scene);
    if (box.isEmpty()) return;
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3()).length();
    camera.position.copy(center).add(new THREE.Vector3(size, size * 0.4, size));
    controls.target.copy(center);
  };

  return {
    dispose() {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      renderer.dispose();
      container.removeChild(renderer.domElement);
    },
    clearResult() {
      resultGroup.clear();
    },
    showModelObject(obj: THREE.Object3D) {
      modelGroup.clear();
      modelGroup.add(obj);
      frameAll();
    },
    async showSurfaceGlb(buffer: ArrayBuffer) {
      resultGroup.clear();
      const gltf = await new GLTFLoader().parseAsync(buffer, "");
      gltf.scene.traverse((o) => {
        const mesh = o as THREE.Mesh;
        if (mesh.isMesh) {
          // 顶点色压力云图：略去纹理光照依赖，保留轻微金属感
          (mesh.material as THREE.MeshStandardMaterial).metalness = 0.0;
          (mesh.material as THREE.MeshStandardMaterial).roughness = 0.8;
        }
      });
      resultGroup.add(gltf.scene);
      frameAll();
    },
    showStreamlines(data) {
      resultGroup.clear();
      for (const line of data.lines) {
        const pts = line.points.map((p) => new THREE.Vector3(p[0], p[1], p[2]));
        if (pts.length < 2) continue;
        const geometry = new THREE.BufferGeometry().setFromPoints(pts);
        const colors: number[] = [];
        for (const s of line.speed) {
          const c = speedColor(s);
          colors.push(c.r, c.g, c.b);
        }
        geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
        const mat = new THREE.LineDashedMaterial({
          vertexColors: true,
          dashSize: 0.25,
          gapSize: 0.15,
        });
        const obj = new THREE.Line(geometry, mat);
        obj.computeLineDistances();
        resultGroup.add(obj);
      }
      if (data.lines.length > 0) frameAll();
    },
    showSlice(data) {
      resultGroup.clear();
      const geometry = new THREE.BufferGeometry();
      const flat: number[] = [];
      for (const p of data.points) flat.push(p[0], p[1], p[2]);
      geometry.setAttribute("position", new THREE.Float32BufferAttribute(flat, 3));
      geometry.setIndex(data.faces.flat());
      const colors: number[] = [];
      for (const c of data.cp) {
        const col = cpColor(c);
        colors.push(col.r, col.g, col.b);
      }
      geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
      geometry.computeVertexNormals();
      const mesh = new THREE.Mesh(
        geometry,
        new THREE.MeshBasicMaterial({
          vertexColors: true,
          side: THREE.DoubleSide,
          transparent: true,
          opacity: 0.85,
        })
      );
      resultGroup.add(mesh);
      frameAll();
    },
    frameAll,
  };
}

// Cp 发散色标（与 solver postprocess.diverging_colormap 一致）
export function cpColor(cp: number): THREE.Color {
  const t = Math.min(1, Math.max(0, (cp + 1.5) / 2.5));
  const blue = new THREE.Color(59 / 255, 76 / 255, 192 / 255);
  const white = new THREE.Color(247 / 255, 247 / 255, 247 / 255);
  const red = new THREE.Color(180 / 255, 4 / 255, 38 / 255);
  if (t < 0.5) return blue.clone().lerp(white, t * 2);
  return white.clone().lerp(red, (t - 0.5) * 2);
}

// 速度色标：低速蓝 -> 高速红
export function speedColor(v: number): THREE.Color {
  const t = Math.min(1, v / 60); // 0-60 m/s
  return new THREE.Color().setHSL((1 - t) * 0.66, 0.8, 0.55);
}

/** 从 File 对象解析 STL/OBJ 并返回 Object3D（浏览器端解析，不经 Rust）。 */
export async function loadModelFile(file: File): Promise<Object3D> {
  const name = file.name.toLowerCase();
  if (name.endsWith(".stl")) {
    const buf = await file.arrayBuffer();
    const geometry = new STLLoader().parse(buf);
    return new THREE.Mesh(geometry, new THREE.MeshStandardMaterial());
  }
  if (name.endsWith(".obj")) {
    const text = await file.text();
    return new OBJLoader().parse(text);
  }
  throw new Error("仅支持 STL/OBJ 文件");
}

type Object3D = THREE.Object3D;
