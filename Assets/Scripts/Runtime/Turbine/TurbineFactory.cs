using System;
using System.Collections.Generic;
using UnityEngine;

namespace Vrar.Turbine
{
    /// <summary>
    /// Builds the notional 3.6 MW turbine from Unity primitives.
    ///
    /// Everything is procedural on purpose: the pilot is zero-paid-asset, and a
    /// procedural rig also means the PlayMode tests can assert the structure
    /// without loading a scene or an imported FBX.
    /// </summary>
    public static class TurbineFactory
    {
        public const float HubHeight = 80f;
        public const float RotorRadius = 60f;
        public const float NacelleLength = 12f;
        public const float NacelleWidth = 4f;
        public const float NacelleHeight = 3f;
        public const int BladeCount = 3;

        private static readonly Dictionary<Color, Material> MaterialCache = new Dictionary<Color, Material>();

        /// <summary>
        /// Shared URP material for a flat colour. Cached so tests can assert identity.
        /// </summary>
        /// <param name="color">Base colour.</param>
        /// <param name="smoothness">
        /// Painted steel, not chrome. URP/Lit defaults to 0.5 smoothness, which is a
        /// half-mirror: any face turned away from the sun then shows only a dark
        /// ambient reflection and reads as black, so the tower and nacelle vanish
        /// against the landscape. Structure is matte.
        /// </param>
        public static Material FlatMaterial(Color color, float smoothness = 0.18f)
        {
            if (MaterialCache.TryGetValue(color, out Material cached) && cached != null)
            {
                return cached;
            }

            Shader shader = Shader.Find("Universal Render Pipeline/Lit")
                            ?? Shader.Find("Standard")
                            ?? Shader.Find("Sprites/Default");

            Material material = new Material(shader) { name = $"Avatar_{ColorUtility.ToHtmlStringRGB(color)}" };
            SetColor(material, color);
            if (material.HasProperty("_Smoothness"))
            {
                material.SetFloat("_Smoothness", smoothness);
            }

            if (material.HasProperty("_Metallic"))
            {
                material.SetFloat("_Metallic", 0f);
            }
            MaterialCache[color] = material;
            return material;
        }

        public static void SetColor(Material material, Color color)
        {
            if (material == null)
            {
                return;
            }

            if (material.HasProperty("_BaseColor"))
            {
                material.SetColor("_BaseColor", color);
            }

            if (material.HasProperty("_Color"))
            {
                material.SetColor("_Color", color);
            }
        }

        /// <summary>Root object with the turbine rig and every avatar attached.</summary>
        public static TurbineRig Build(string name = "WindTurbineRig")
        {
            GameObject root = new GameObject(name);

            // Structural members are grey: they are the machine, not the avatars.
            Material structure = FlatMaterial(new Color(0.86f, 0.87f, 0.89f));
            Material dark = FlatMaterial(new Color(0.30f, 0.32f, 0.35f));

            // --- tower ---------------------------------------------------------
            Primitive(root.transform, "Tower", PrimitiveType.Cylinder, structure,
                new Vector3(0f, HubHeight / 2f, 0f), new Vector3(6f, HubHeight / 2f, 6f));

            // --- nacelle -------------------------------------------------------
            GameObject nacelle = Primitive(
                root.transform, "Nacelle", PrimitiveType.Cube, structure,
                new Vector3(0f, HubHeight, 0f),
                new Vector3(NacelleWidth, NacelleHeight, NacelleLength));

            // The nacelle mesh is scaled, and a child inherits its parent's scale, so the
            // drive train is parented to the rig root: metres here are metres out.
            var driveTrain = new GameObject("DriveTrain");
            driveTrain.transform.SetParent(root.transform, false);
            driveTrain.transform.localPosition = new Vector3(0f, HubHeight, 0f);
            Transform train = driveTrain.transform;

            // Drive train along +Z, mounted on top of the nacelle so every avatar stays
            // visible: a sealed housing would hide the very thing the PoC shows.
            GameObject bearing = Primitive(
                train, "MainBearing", PrimitiveType.Cylinder, dark,
                new Vector3(0f, 1.7f, 2.6f), new Vector3(1.8f, 1.1f, 1.8f));
            bearing.transform.localRotation = Quaternion.Euler(90f, 0f, 0f);

            GameObject gearbox = Primitive(
                train, "Gearbox", PrimitiveType.Cube, dark,
                new Vector3(0f, 2.4f, 0.4f), new Vector3(3f, 3f, 2.6f));

            GameObject generator = Primitive(
                train, "Generator", PrimitiveType.Cylinder, dark,
                new Vector3(0f, 1.8f, -3.2f), new Vector3(2.6f, 1.7f, 2.6f));
            generator.transform.localRotation = Quaternion.Euler(90f, 0f, 0f);

            GameObject pitch = Primitive(
                train, "PitchSystem", PrimitiveType.Sphere, dark,
                new Vector3(0f, 1.4f, 4.2f), new Vector3(1.4f, 1.1f, 1.4f));

            // --- rotor ---------------------------------------------------------
            GameObject rotorObject = new GameObject("Rotor");
            rotorObject.transform.SetParent(train, false);
            rotorObject.transform.localPosition = new Vector3(0f, 0f, NacelleLength / 2f + 1.2f);

            Transform rotor = rotorObject.transform;
            Primitive(rotor, "Hub", PrimitiveType.Sphere, structure,
                Vector3.zero, new Vector3(5f, 5f, 5f));

            // The blade set is its own avatar host so its expression colours the
            // blades only, never the whole machine.
            var bladeSet = new GameObject("BladeSet");
            bladeSet.transform.SetParent(rotor, false);

            var blades = new List<Transform>();
            for (int i = 0; i < BladeCount; i++)
            {
                // Unity's cube is one unit across, so the scale is the blade's size
                // in metres: a RotorRadius-long blade centred RotorRadius/2 above
                // the hub puts the root at the hub and the tip RotorRadius out.
                GameObject blade = Primitive(
                    bladeSet.transform, $"Blade_{i + 1}", PrimitiveType.Cube, structure,
                    Vector3.zero, new Vector3(2.6f, RotorRadius, 0.5f));
                blade.transform.localPosition = new Vector3(0f, RotorRadius / 2f + 1.5f, 0f);
                blade.transform.localRotation = Quaternion.Euler(0f, 0f, i * (360f / BladeCount));
                blades.Add(blade.transform);
            }

            var avatars = new List<Avatar.ComponentAvatar>
            {
                AvatarFor(bladeSet, "blade_set", "Blade Set"),
                AvatarFor(bearing, "main_bearing", "Main Bearing"),
                AvatarFor(gearbox, "gearbox", "Gearbox"),
                AvatarFor(generator, "generator", "Generator"),
                AvatarFor(pitch, "pitch_system", "Pitch System"),
            };

            TurbineRig rig = root.AddComponent<TurbineRig>();
            rig.Assign(avatars, rotor, bladeSet.transform, blades);
            return rig;
        }

        private static Avatar.ComponentAvatar AvatarFor(GameObject host, string id, string label)
        {
            Renderer[] renderers = host.GetComponentsInChildren<Renderer>();
            foreach (Renderer renderer in renderers)
            {
                GiveAvatarMaterial(renderer, id);
            }

            Avatar.ComponentAvatar avatar = host.AddComponent<Avatar.ComponentAvatar>();
            avatar.Configure(id, label, renderers);
            return avatar;
        }

        /// <summary>
        /// Give an avatar renderer its own material with emission enabled.
        ///
        /// Both steps must happen at build time on a private copy. Avatars colour
        /// themselves through a MaterialPropertyBlock, but URP ignores
        /// <c>_EmissionColor</c> while the <c>_EMISSION</c> keyword is off — and
        /// toggling that keyword on a material shared with the rest of the rig
        /// mutates the shared material's shader state for every other user.
        /// </summary>
        private static void GiveAvatarMaterial(Renderer renderer, string componentId)
        {
            Material source = renderer.sharedMaterial;
            if (source == null)
            {
                return;
            }

            var material = new Material(source) { name = $"{componentId}_avatar" };
            material.EnableKeyword("_EMISSION");
            renderer.sharedMaterial = material;
        }

        public static GameObject Primitive(
            Transform parent, string name, PrimitiveType type, Material material, Vector3 localPosition, Vector3 localScale)
        {
            GameObject gameObject = GameObject.CreatePrimitive(type);
            gameObject.name = name;
            gameObject.transform.SetParent(parent, false);
            gameObject.transform.localPosition = localPosition;
            gameObject.transform.localScale = localScale;

            Collider collider = gameObject.GetComponent<Collider>();
            if (collider != null)
            {
                // Tremor animates transforms; a collider would turn that into
                // physics jitter and wasted broadphase work.
                if (Application.isPlaying)
                {
                    UnityEngine.Object.Destroy(collider);
                }
                else
                {
                    UnityEngine.Object.DestroyImmediate(collider);
                }
            }

            MeshRenderer meshRenderer = gameObject.GetComponent<MeshRenderer>();
            if (material != null)
            {
                meshRenderer.sharedMaterial = material;
            }

            return gameObject;
        }

        /// <summary>A neutral ground disc so scale and depth read correctly.</summary>
        public static GameObject BuildGround(float radius = 260f)
        {
            GameObject holder = new GameObject("Ground");
            // Unity's cylinder is 1 unit across and 2 units tall.
            Primitive(holder.transform, "Ground", PrimitiveType.Cylinder,
                FlatMaterial(new Color(0.19f, 0.23f, 0.20f)),
                new Vector3(0f, -0.25f, 0f), new Vector3(radius * 2f, 0.25f, radius * 2f));
            return holder;
        }
    }
}