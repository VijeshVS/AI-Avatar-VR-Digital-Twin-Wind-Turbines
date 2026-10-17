using System.IO;
using UnityEditor;
using UnityEngine;
using Vrar.Environment;

namespace Vrar.EditorTools
{
    /// <summary>
    /// Import settings for the downloaded CC0 environment assets, applied in code
    /// so the repository carries no per-asset manual setup and a clean checkout
    /// configures itself.
    ///
    /// Every texture is set to repeat wrapping with normal maps left uncompressed:
    /// terrain is tiled across kilometres, and DXT compression on a normal map
    /// breaks the unpack the terrain shader relies on.
    /// </summary>
    public static class EnvironmentAssets
    {
        public const string TextureDirectory = "Assets/Environment/Textures";
        public const string SkyPath = "Assets/Environment/Sky/hilly_terrain_sky.hdr";
        public const string TerrainShaderName = "VRAR/TerrainBlend";
        public const string GrassShaderName = "VRAR/GrassWind";

        /// <summary>Grass budget. Tufts x 3 blades x 4 triangles is the cost.</summary>
        private const int GrassTufts = 20000;

        /// <summary>How far out from the site grass is placed, in metres.</summary>
        private const float GrassReach = 850f;

        /// <summary>Distance at which grass density has halved.</summary>
        private const float GrassFalloff = 110f;

        private static readonly string[] GrassMaterials = { "grass_ground_diff" };
        private static readonly string[] RockMaterials = { "aerial_rocks_04_diff" };
        private static readonly string[] DirtMaterials = { "brown_mud_02_diff" };

        /// <summary>Configure every environment texture. Safe to call repeatedly.</summary>
        public static void ConfigureImporters()
        {
            foreach (string path in Directory.GetFiles(TextureDirectory, "*.jpg", SearchOption.AllDirectories))
            {
                ConfigureTexture(path);
            }

            if (File.Exists(SkyPath))
            {
                ConfigureSky();
            }
        }

        private static void ConfigureTexture(string path)
        {
            var importer = AssetImporter.GetAtPath(path) as TextureImporter;
            if (importer == null)
            {
                return;
            }

            bool isNormal = Path.GetFileName(path).Contains("_nor_gl");

            importer.textureType = isNormal ? TextureImporterType.NormalMap : TextureImporterType.Default;
            importer.wrapMode = TextureWrapMode.Repeat;
            importer.filterMode = FilterMode.Bilinear;
            importer.mipmapEnabled = true;

            // The ground is seen from tens of metres to a kilometre away. Mip
            // levels plus trilinear filtering are what keep it from shimmering;
            // aniso is the difference between a field and static.
            importer.anisoLevel = 8;

            var settings = new TextureImporterPlatformSettings
            {
                name = "Default",
                maxTextureSize = 1024,
                textureCompression = TextureImporterCompression.Compressed
            };
            importer.SetPlatformTextureSettings(settings);

            importer.SaveAndReimport();
        }

        private static void ConfigureSky()
        {
            var importer = AssetImporter.GetAtPath(SkyPath) as TextureImporter;
            if (importer == null)
            {
                return;
            }

            // A skybox only needs RGB. Loading the HDR as float would quadruple the
            // resident memory for data the sky shader never samples.
            importer.textureType = TextureImporterType.Default;
            importer.sRGBTexture = true;
            importer.mipmapEnabled = false;
            importer.wrapMode = TextureWrapMode.Clamp;
            importer.maxTextureSize = 1024;

            var settings = new TextureImporterPlatformSettings
            {
                name = "Default",
                maxTextureSize = 1024,
                textureCompression = TextureImporterCompression.Uncompressed
            };
            importer.SetPlatformTextureSettings(settings);

            importer.SaveAndReimport();
        }

        public static Shader TerrainShader()
        {
            return Shader.Find(TerrainShaderName);
        }

        /// <summary>
        /// Build the terrain material from the imported maps. Returns null when
        /// the assets are missing so the scene builder can fall back rather than
        /// producing a magenta surface.
        /// </summary>
        public static Material BuildTerrainMaterial()
        {
            Shader shader = TerrainShader();
            if (shader == null)
            {
                Debug.LogWarning($"[VRAR] shader '{TerrainShaderName}' not found; terrain will be untextured.");
                return null;
            }

            var material = new Material(shader) { name = "TerrainBlend" };

            // Poly Haven's grass_ground is dry, straw-coloured upland grass, which
            // reads as bare soil next to the rock. Tinting it back toward green is
            // cheaper and more controllable than hunting for another map.
            material.SetColor("_GrassTint", new Color(0.72f, 1.05f, 0.46f));
            material.SetColor("_RockTint", new Color(0.92f, 0.94f, 0.98f));
            material.SetFloat("_NormalStrength", 1.35f);
            material.SetFloat("_MacroStrength", 0.32f);

            Assign(material, "_GrassDiff", GrassMaterials);
            Assign(material, "_RockDiff", RockMaterials);
            Assign(material, "_DirtDiff", DirtMaterials);
            Assign(material, "_GrassNormal", new[] { "grass_ground_nor_gl" });
            Assign(material, "_RockNormal", new[] { "aerial_rocks_04_nor_gl" });
            Assign(material, "_DirtNormal", new[] { "brown_mud_02_nor_gl" });

            return material;
        }

        private static void Assign(Material material, string property, string[] files)
        {
            foreach (string file in files)
            {
                string path = $"{TextureDirectory}/{file}.jpg";
                var texture = AssetDatabase.LoadAssetAtPath<Texture2D>(path);
                if (texture == null)
                {
                    continue;
                }

                material.SetTexture(property, texture);
                material.SetTextureScale(property, Vector2.one);
                return;
            }
        }

        /// <summary>Flat URP materials for the vegetation and boulders.</summary>
        /// <summary>Material for the wind-animated grass field.</summary>
        public static Material BuildGrassMaterial()
        {
            Shader shader = Shader.Find(GrassShaderName);
            if (shader == null)
            {
                Debug.LogWarning($"[VRAR] shader '{GrassShaderName}' not found; grass will be skipped.");
                return null;
            }

            var material = new Material(shader) { name = "GrassWind" };
            // Olive rather than saturated green: at this density a vivid green
            // vibrates against the terrain texture underneath it.
            material.SetColor("_BaseColor", new Color(0.21f, 0.28f, 0.13f, 1f));
            material.SetColor("_TipColor", new Color(0.40f, 0.47f, 0.24f, 1f));
            material.SetFloat("_WindStrength", 0.55f);
            material.SetFloat("_WindSpeed", 1.4f);
            material.SetVector("_WindDirection", new Vector4(0.82f, 0f, 0.57f, 0f));
            // Tussock grass rather than lawn: at a fixed triangle budget the only
            // way to get real coverage is fewer, larger blades, so the blades are
            // sized to read from the overview camera rather than to look right
            // underfoot.
            material.SetFloat("_BladeHeight", 1.5f);
            // Fades much further than before, because the field is no longer a
            // patch in front of the lens: grass now has to survive out to the
            // horizon to read as a landscape rather than a lawn.
            material.SetFloat("_FadeStart", 90f);
            material.SetFloat("_FadeEnd", 330f);
            material.enableInstancing = true;
            return material;
        }

        public static Material BuildPropMaterial(string name, Color color, float smoothness)
        {
            Shader shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
            var material = new Material(shader) { name = name };
            if (material.HasProperty("_BaseColor"))
            {
                material.SetColor("_BaseColor", color);
            }

            if (material.HasProperty("_Smoothness"))
            {
                material.SetFloat("_Smoothness", smoothness);
            }

            return material;
        }

        /// <summary>
        /// Point the scene at the HDRI sky and let it drive ambient light, so the
        /// landscape is lit by the same sky it is seen against.
        /// </summary>
        public static void ApplySkybox()
        {
            var sky = AssetDatabase.LoadAssetAtPath<Texture2D>(SkyPath);
            Shader shader = Shader.Find("Skybox/Panoramic");
            if (sky == null || shader == null)
            {
                Debug.LogWarning("[VRAR] skybox assets missing; keeping the default sky.");
                return;
            }

            var material = new Material(shader) { name = "EnvironmentSky" };
            material.SetTexture("_MainTex", sky);

            RenderSettings.skybox = material;
            RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Trilight;
            RenderSettings.ambientSkyColor = new Color(0.48f, 0.55f, 0.64f);
            RenderSettings.ambientEquatorColor = new Color(0.32f, 0.34f, 0.33f);
            RenderSettings.ambientGroundColor = new Color(0.15f, 0.16f, 0.15f);
            RenderSettings.fog = true;
            RenderSettings.fogMode = FogMode.Linear;
            RenderSettings.fogStartDistance = 320f;
            RenderSettings.fogEndDistance = 1500f;
            RenderSettings.fogColor = new Color(0.62f, 0.70f, 0.80f);
        }

        /// <summary>Terrain, props and sky, in that order.</summary>
        public static void BuildLandscape(Vector3 viewpoint)
        {
            ConfigureImporters();
            ApplySkybox();

            Material terrain = BuildTerrainMaterial();
            GameObject ground = TerrainBuilder.Build(TerrainShader(), terrain);
            ground.transform.position = Vector3.zero;

            // Everything generated here shares one parent so the landscape can be
            // cleared or regenerated as a unit.
            var holder = new GameObject("Landscape");

            Material foliage = BuildPropMaterial("ConiferFoliage", new Color(0.13f, 0.24f, 0.11f), 0.05f);
            Material bark = BuildPropMaterial("ConiferBark", new Color(0.24f, 0.18f, 0.13f), 0.04f);
            Material rock = BuildPropMaterial("BoulderRock", new Color(0.42f, 0.41f, 0.39f), 0.08f);
            LandscapeProps.Build(foliage, bark, rock, Vector3.zero, viewpoint);

            // Baked across the whole map rather than in a disc around the camera,
            // so the landscape is grassy everywhere the terrain will take it.
            GrassField.Build(BuildGrassMaterial(), GrassTufts, GrassReach, GrassFalloff,
                Vector3.zero, viewpoint);

            Livestock.Build(Vector3.zero, viewpoint);
        }
    }
}