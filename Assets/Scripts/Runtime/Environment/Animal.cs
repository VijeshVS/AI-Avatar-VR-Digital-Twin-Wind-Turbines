using System.Collections.Generic;
using UnityEngine;

namespace Vrar.Environment
{
    /// <summary>
    /// A grazing animal built from primitives, with a wander behaviour and a
    /// procedural walk.
    ///
    /// Built in code rather than imported because the CC0 catalogues reachable
    /// without a browser session carry no Unity-native animated quadrupeds: the
    /// Kenney animal pack is PNG sprites only, and the CC0 GitHub animal repos use
    /// minetest's .b3d, which Unity does not import (PRD FR-1.2). Everything here
    /// is therefore licence-clean by construction, and the animation is driven by
    /// the same code that moves the animal, so gait and speed can never disagree.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class Animal : MonoBehaviour
    {
        private enum State
        {
            Graze,
            Walk
        }

        [SerializeField, Min(0.1f)] private float _walkSpeed = 1.4f;
        [SerializeField, Min(0f)] private float _homeRadius = 90f;
        [SerializeField, Min(0.05f)] private float _turnRate = 110f;
        [SerializeField] private Vector3 _home;
        [SerializeField] private int _seed = 1;

        private Transform[] _legs = new Transform[4];
        private Transform _head;
        private Vector3 _bodyRest;
        private State _state;
        private Vector3 _target;
        private float _stateTimer;
        private float _legPhase;
        private float _grazeAmount;
        private System.Random _random;

        public static Animal Spawn(Transform parent, Vector3 position, float scale,
            Color bodyColour, float walkSpeed, int seed)
        {
            var holder = new GameObject("Animal");
            holder.transform.SetParent(parent, false);
            holder.transform.position = position;
            holder.transform.localScale = Vector3.one * scale;
            holder.transform.rotation = Quaternion.Euler(0f, (seed * 37f) % 360f, 0f);

            var animal = holder.AddComponent<Animal>();
            animal._walkSpeed = walkSpeed;
            animal._seed = seed;
            animal._home = position;
            animal.BuildBody(bodyColour);
            animal.ResetWander(seed);
            return animal;
        }

        private void Awake()
        {
            _random = new System.Random(_seed == 0 ? 1 : _seed);
        }

        private void Update()
        {
            float deltaTime = Time.deltaTime;

            // A grazing animal lowers its head; the blend is what stops the
            // switch between states from snapping.
            _grazeAmount = Mathf.MoveTowards(_grazeAmount, _state == State.Graze ? 1f : 0f, deltaTime * 1.6f);

            float speed = _state == State.Walk ? _walkSpeed : 0f;
            MoveTowardsTarget(deltaTime, speed);
            Animate(deltaTime, speed);
        }

        private void ResetWander(int seed)
        {
            var random = new System.Random(seed * 7919 + 13);
            _state = State.Graze;
            _stateTimer = 1.5f + (float)random.NextDouble() * 5f;
            _target = transform.position;
        }

        private void MoveTowardsTarget(float deltaTime, float speed)
        {
            if (_state == State.Walk)
            {
                Vector3 flat = target3D() - transform.position;
                flat.y = 0f;
                float distance = flat.magnitude;

                if (distance < 1.5f)
                {
                    _state = State.Graze;
                    _stateTimer = 2f + (float)_random.NextDouble() * 7f;
                    return;
                }

                Vector3 direction = flat / distance;
                Vector3 heading = transform.forward;
                heading.y = 0f;
                heading.Normalize();

                float turn = Vector3.SignedAngle(heading, direction, Vector3.up);
                transform.Rotate(0f, Mathf.Clamp(turn, -1f, 1f) * _turnRate * deltaTime, 0f);

                transform.position += transform.forward * speed * deltaTime;
                transform.position = new Vector3(
                    transform.position.x,
                    TerrainBuilder.HeightAt(transform.position.x, transform.position.z),
                    transform.position.z);
                return;
            }

            _stateTimer -= deltaTime;
            if (_stateTimer > 0f)
            {
                return;
            }

            // Pick a new spot inside the herd's home range and walk to it. A
            // grazing herd drifts slowly around its range rather than pacing.
            float angle = (float)_random.NextDouble() * Mathf.PI * 2f;
            float radius = Mathf.Sqrt((float)_random.NextDouble()) * _homeRadius;
            _target = new Vector3(
                _home.x + Mathf.Cos(angle) * radius,
                0f,
                _home.z + Mathf.Sin(angle) * radius);
            _target.y = TerrainBuilder.HeightAt(_target.x, _target.z);
            _state = State.Walk;
        }

        private Vector3 target3D() => new Vector3(_target.x, transform.position.y, _target.z);

        /// <summary>
        /// Diagonal gait — the front-left and rear-right legs swing together,
        /// which is what a quadruped actually does. Phase is driven by distance
        /// travelled rather than time, so the feet do not skate when the animal
        /// changes speed.
        /// </summary>
        private void Animate(float deltaTime, float speed)
        {
            _legPhase += deltaTime * speed * 2.6f;

            for (int i = 0; i < _legs.Length; i++)
            {
                if (_legs[i] == null)
                {
                    continue;
                }

                // Diagonal pairs share a phase; the pairs are half a cycle apart.
                float offset = i is 0 or 3 ? 0f : Mathf.PI;
                float swing = Mathf.Sin(_legPhase + offset) * 26f;
                _legs[i].localRotation = Quaternion.Euler(swing, 0f, 0f);
            }

            if (_bodyRest != Vector3.zero)
            {
                // Vertical bob at twice the stride, plus a graze dip.
                float bob = Mathf.Sin(_legPhase * 2f) * 0.035f * Mathf.Clamp01(speed);
                var body = transform.GetChild(0);
                if (body != null)
                {
                    body.localPosition = _bodyRest +
                                        new Vector3(0f, bob - _grazeAmount * 0.35f, 0f);
                }
            }

            if (_head != null)
            {
                float target = Mathf.Lerp(0f, 52f, _grazeAmount);
                _head.localRotation = Quaternion.Euler(
                    Mathf.LerpAngle(_head.localEulerAngles.x, target, deltaTime * 3f), 0f, 0f);
            }
        }

        private void BuildBody(Color bodyColour)
        {
            Material material = LivestockMaterial(bodyColour);

            var body = new GameObject("Body");
            body.transform.SetParent(transform, false);
            body.transform.localPosition = new Vector3(0f, 1.05f, 0f);
            _bodyRest = body.transform.localPosition;

            AddBox(body.transform, new Vector3(0f, 0f, 0f), new Vector3(0.62f, 0.62f, 1.35f), material);
            AddBox(body.transform, new Vector3(0f, 0.28f, -0.55f), new Vector3(0.5f, 0.36f, 0.5f), material);

            // Neck and head as a separate pivot so grazing can dip them.
            var neck = new GameObject("Neck");
            neck.transform.SetParent(body.transform, false);
            neck.transform.localPosition = new Vector3(0f, 0.2f, 0.6f);

            AddBox(neck.transform, new Vector3(0f, 0.28f, 0.18f), new Vector3(0.26f, 0.62f, 0.3f), material);
            AddBox(neck.transform, new Vector3(0f, 0.62f, 0.34f), new Vector3(0.28f, 0.3f, 0.52f), material);
            foreach (int side in new[] { -1, 1 })
            {
                AddBox(neck.transform, new Vector3(side * 0.17f, 0.55f, 0.72f),
                    new Vector3(0.05f, 0.16f, 0.1f), material);
            }

            _head = neck.transform;

            // Legs pivot from the top so they swing from the hip, not the foot.
            for (int i = 0; i < 4; i++)
            {
                bool front = i < 2;
                float x = (i % 2 == 0 ? -1f : 1f) * 0.24f;
                float z = front ? 0.45f : -0.48f;

                var leg = new GameObject($"Leg{i}");
                leg.transform.SetParent(body.transform, false);
                leg.transform.localPosition = new Vector3(x, -0.18f, z);
                AddBox(leg.transform, new Vector3(0f, -0.32f, 0f), new Vector3(0.16f, 0.66f, 0.18f), material);
                _legs[i] = leg.transform;
            }

            var tail = new GameObject("Tail");
            tail.transform.SetParent(body.transform, false);
            tail.transform.localPosition = new Vector3(0f, 0.18f, -0.76f);
            AddBox(tail.transform, new Vector3(0f, -0.14f, -0.06f), new Vector3(0.08f, 0.34f, 0.08f), material);
        }

        private static readonly Dictionary<Color, Material> MaterialCache = new Dictionary<Color, Material>();

        /// <summary>Matte coat: a smooth dielectric at livestock scale reads as plastic.</summary>
        private static Material LivestockMaterial(Color colour)
        {
            if (MaterialCache.TryGetValue(colour, out Material cached) && cached != null)
            {
                return cached;
            }

            Shader shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
            var material = new Material(shader) { name = $"Coat_{ColorUtility.ToHtmlStringRGB(colour)}" };
            if (material.HasProperty("_BaseColor"))
            {
                material.SetColor("_BaseColor", colour);
            }

            if (material.HasProperty("_Smoothness"))
            {
                material.SetFloat("_Smoothness", 0.12f);
            }

            MaterialCache[colour] = material;
            return material;
        }

        private static void AddBox(Transform parent, Vector3 local, Vector3 size, Material material)
        {
            var cube = GameObject.CreatePrimitive(PrimitiveType.Cube);
            cube.name = "Part";
            cube.transform.SetParent(parent, false);
            cube.transform.localPosition = local;
            cube.transform.localScale = size;

            Collider collider = cube.GetComponent<Collider>();
            if (collider != null)
            {
                // These are built at scene-build time, in edit mode, where Destroy
                // is deferred and unsafe: the colliders would outlive the scene
                // they belonged to and crash the runtime. Matches the guard in
                // TurbineFactory.Primitive.
                if (Application.isPlaying)
                {
                    Destroy(collider);
                }
                else
                {
                    DestroyImmediate(collider);
                }
            }

            cube.GetComponent<MeshRenderer>().sharedMaterial = material;
        }
    }
}