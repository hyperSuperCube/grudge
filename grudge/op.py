"""
.. autofunction:: project
.. autofunction:: nodes

.. autofunction:: local_grad
.. autofunction:: local_d_dx
.. autofunction:: local_div

.. autofunction:: weak_local_grad
.. autofunction:: weak_local_d_dx
.. autofunction:: weak_local_div

.. autofunction:: normal
.. autofunction:: mass
.. autofunction:: inverse_mass
.. autofunction:: face_mass

.. autofunction:: norm
.. autofunction:: nodal_sum
.. autofunction:: nodal_min
.. autofunction:: nodal_max

.. autofunction:: interior_trace_pair
.. autofunction:: cross_rank_trace_pairs
"""

__copyright__ = """
Copyright (C) 2021 Andreas Kloeckner
Copyright (C) 2021 University of Illinois Board of Trustees
"""

__license__ = """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""


from numbers import Number
from pytools import (
    memoize_in,
    memoize_on_first_arg,
    keyed_memoize_in
)
from pytools.obj_array import obj_array_vectorize
from meshmode.array_context import (
    FirstAxisIsElementsTag, make_loopy_program
)
from meshmode.dof_array import DOFArray

import numpy as np
import grudge.dof_desc as dof_desc

from meshmode.mesh import BTAG_ALL, BTAG_NONE, BTAG_PARTITION  # noqa
from meshmode.dof_array import freeze, flatten, unflatten

from grudge.symbolic.primitives import TracePair
from grudge import sym, bind


# {{{ tags

class HasElementwiseMatvecTag(FirstAxisIsElementsTag):
    pass


class MassOperatorTag(HasElementwiseMatvecTag):
    pass

# }}}


# {{{ Interpolation and projection

def interp(dcoll, src, tgt, vec):
    from warnings import warn
    warn("using 'interp' is deprecated, use 'project' instead.",
            DeprecationWarning, stacklevel=2)

    return project(dcoll, src, tgt, vec)


def project(dcoll, src, tgt, vec):
    """Project from one discretization to another, e.g. from the
    volume to the boundary, or from the base to the an overintegrated
    quadrature discretization.

    :arg src: a :class:`~grudge.dof_desc.DOFDesc`, or a value convertible to one
    :arg tgt: a :class:`~grudge.dof_desc.DOFDesc`, or a value convertible to one
    :arg vec: a :class:`~meshmode.dof_array.DOFArray`
    """
    src = dof_desc.as_dofdesc(src)
    tgt = dof_desc.as_dofdesc(tgt)
    if src == tgt:
        return vec

    if isinstance(vec, np.ndarray):
        return obj_array_vectorize(
                lambda el: project(dcoll, src, tgt, el), vec)

    if isinstance(vec, Number):
        return vec

    return dcoll.connection_from_dds(src, tgt)(vec)

# }}}


# {{{ geometric properties

def nodes(dcoll, dd=None):
    r"""Return the nodes of a discretization.

    :arg dd: a :class:`~grudge.dof_desc.DOFDesc`, or a value convertible to one.
        Defaults to the base volume discretization.
    :returns: an object array of :class:`~meshmode.dof_array.DOFArray`\ s
    """
    if dd is None:
        return dcoll._volume_discr.nodes()
    else:
        return dcoll.discr_from_dd(dd).nodes()


@memoize_on_first_arg
def normal(dcoll, dd):
    """Get the unit normal to the specified surface discretization, *dd*.

    :arg dd: a :class:`~grudge.dof_desc.DOFDesc` as the surface discretization.
    :returns: an object array of :class:`~meshmode.dof_array.DOFArray`.
    """
    from grudge.geometry import normal

    actx = dcoll.discr_from_dd(dd)._setup_actx
    return freeze(normal(actx, dcoll, dd))

# }}}


# {{{ Derivative operators

def reference_derivative_matrices(actx, element_group):
    @keyed_memoize_in(
        actx, reference_derivative_matrices,
        lambda grp: grp.discretization_key())
    def get_ref_derivative_mats(grp):
        from meshmode.discretization.poly_element import diff_matrices
        return actx.freeze(
            actx.from_numpy(
                np.asarray(
                    [dfmat for dfmat in diff_matrices(grp)]
                )
            )
        )
    return get_ref_derivative_mats(element_group)


def _compute_local_gradient(dcoll, vec, xyz_axis):
    from grudge.geometry import \
        inverse_surface_metric_derivative

    discr = dcoll.discr_from_dd(dof_desc.DD_VOLUME)
    actx = vec.array_context

    # Convert to 3D tensor
    # FIXME: Is there a better/more efficient way to do this?
    inverse_jac_t = actx.from_numpy(
        np.asarray(
            [actx.to_numpy(
                inverse_surface_metric_derivative(
                    actx, dcoll, rst_axis, xyz_axis
                )[0]
            ) for rst_axis in range(dcoll.dim)]
        )
    )
    return DOFArray(
        actx,
        data=tuple(
            actx.einsum("dij,ej,dej->ei",
                        reference_derivative_matrices(actx, grp),
                        vec_i,
                        inverse_jac_t,
                        arg_names=("ref_diff_mat", "vec", "inv_jac_t"),
                        tagged=(HasElementwiseMatvecTag(),))

            for grp, vec_i in zip(discr.groups, vec)
        )
    )


def local_grad(dcoll, vec):
    r"""Return the element-local gradient of the volume function represented by
    *vec*.

    :arg vec: a :class:`~meshmode.dof_array.DOFArray`
    :returns: an object array of :class:`~meshmode.dof_array.DOFArray`\ s
    """
    from pytools.obj_array import make_obj_array
    return make_obj_array(
        [_compute_local_gradient(dcoll, vec, xyz_axis)
         for xyz_axis in range(dcoll.dim)]
    )


def local_d_dx(dcoll, xyz_axis, vec):
    r"""Return the element-local derivative along axis *xyz_axis* of the volume
    function represented by *vec*.

    :arg xyz_axis: an integer indicating the axis along which the derivative
        is taken
    :arg vec: a :class:`~meshmode.dof_array.DOFArray`
    :returns: a :class:`~meshmode.dof_array.DOFArray`\ s
    """
    return _compute_local_gradient(dcoll, vec, xyz_axis)


def _div_helper(dcoll, diff_func, vecs):
    if not isinstance(vecs, np.ndarray):
        raise TypeError("argument must be an object array")
    assert vecs.dtype == object

    if vecs.shape[-1] != dcoll.ambient_dim:
        raise ValueError(
            "last dimension of *vecs* argument must match "
            "ambient dimension"
        )

    if len(vecs.shape) == 1:
        return sum(diff_func(i, vec_i) for i, vec_i in enumerate(vecs))
    else:
        result = np.zeros(vecs.shape[:-1], dtype=object)
        for idx in np.ndindex(vecs.shape[:-1]):
            result[idx] = \
                sum(diff_func(i, vec_i) for i, vec_i in enumerate(vecs[idx]))
        return result


def local_div(dcoll, vecs):
    r"""Return the element-local divergence of the vector volume function
    represented by *vecs*.

    :arg vec: an object array of
        a :class:`~meshmode.dof_array.DOFArray`\ s,
        where the last axis of the array must have length
        matching the volume dimension.
    :returns: a :class:`~meshmode.dof_array.DOFArray`
    """

    return _div_helper(
        dcoll,
        lambda i, subvec: local_d_dx(dcoll, i, subvec),
        vecs
    )

# }}}


# {{{ Weak derivative operators

def reference_stiffness_transpose_matrix(actx, out_element_group, in_element_group):
    @keyed_memoize_in(
        actx, reference_stiffness_transpose_matrix,
        lambda out_grp, in_grp: (out_grp.discretization_key(),
                                 in_grp.discretization_key()))
    def get_ref_stiffness_transpose_mat(out_grp, in_grp):
        if in_grp == out_grp:
            mmat = reference_mass_matrix(actx, out_grp, in_grp)

            return actx.freeze(
                actx.from_numpy(
                    np.asarray(
                        [actx.to_numpy(dmat.T).dot(actx.to_numpy(mmat.T))
                         for dmat in reference_derivative_matrices(actx, in_grp)]
                    )
                )
            )

        from modepy import vandermonde
        basis = out_grp.basis_obj()
        vand = vandermonde(basis.functions, out_grp.unit_nodes)
        grad_vand = vandermonde(basis.gradients, in_grp.unit_nodes)
        vand_inv_t = np.linalg.inv(vand).T

        if not isinstance(grad_vand, tuple):
            # NOTE: special case for 1d
            grad_vand = (grad_vand,)

        weights = in_grp.quadrature_rule().weights
        return actx.freeze(
            actx.from_numpy(
                np.einsum(
                    "c,bz,acz->abc",
                    weights,
                    vand_inv_t,
                    grad_vand
                ).copy()  # contigify the array
            )
        )
    return get_ref_stiffness_transpose_mat(out_element_group,
                                           in_element_group)


def _apply_stiffness_transpose_operator(dcoll, dd_out, dd_in, vec, xyz_axis):
    from grudge.geometry import \
        inverse_surface_metric_derivative, area_element

    in_discr = dcoll.discr_from_dd(dd_in)
    out_discr = dcoll.discr_from_dd(dd_out)

    actx = vec.array_context
    area_elements = area_element(actx, dcoll, dd=dd_in)
    # Convert to 3D tensor
    # FIXME: Is there a better/more efficient way to do this?
    inverse_jac_t = actx.from_numpy(
        np.asarray(
            [actx.to_numpy(
                inverse_surface_metric_derivative(
                    actx, dcoll, rst_axis, xyz_axis, dd=dd_in
                )[0]
            ) for rst_axis in range(dcoll.dim)]
        )
    )
    return DOFArray(
        actx,
        data=tuple(
            actx.einsum("dej,dij,ej,ej->ei",
                        inverse_jac_t,
                        reference_stiffness_transpose_matrix(
                            actx,
                            out_element_group=out_grp,
                            in_element_group=in_grp
                        ),
                        vec_i,
                        ae_i,
                        arg_names=("inv_jac_t", "ref_stiffT_mat", "vec", "jac"),
                        tagged=(HasElementwiseMatvecTag(),))

            for out_grp, in_grp, vec_i, ae_i in zip(out_discr.groups,
                                                    in_discr.groups,
                                                    vec,
                                                    area_elements)
        )
    )


def weak_local_grad(dcoll, *args):
    r"""Return the element-local weak gradient of the volume function
    represented by *vec*.

    May be called with ``(vecs)`` or ``(dd, vecs)``.

    :arg dd: a :class:`~grudge.dof_desc.DOFDesc`, or a value convertible to one.
        Defaults to the base volume discretization if not provided.
    :arg vec: a :class:`~meshmode.dof_array.DOFArray`
    :returns: an object array of :class:`~meshmode.dof_array.DOFArray`\ s
    """
    if len(args) == 1:
        vec, = args
        dd = dof_desc.DOFDesc("vol", dof_desc.DISCR_TAG_BASE)
    elif len(args) == 2:
        dd, vec = args
    else:
        raise TypeError("invalid number of arguments")

    from pytools.obj_array import make_obj_array

    return make_obj_array(
        [_apply_stiffness_transpose_operator(dcoll,
                                             dof_desc.DD_VOLUME,
                                             dd, vec, xyz_axis)
         for xyz_axis in range(dcoll.dim)]
    )


def weak_local_d_dx(dcoll, *args):
    r"""Return the element-local weak derivative along axis *xyz_axis* of the
    volume function represented by *vec*.

    May be called with ``(xyz_axis, vecs)`` or ``(dd, xyz_axis, vecs)``.

    :arg xyz_axis: an integer indicating the axis along which the derivative
        is taken
    :arg vec: a :class:`~meshmode.dof_array.DOFArray`
    :returns: a :class:`~meshmode.dof_array.DOFArray`\ s
    """
    if len(args) == 2:
        xyz_axis, vec = args
        dd = dof_desc.DOFDesc("vol", dof_desc.DISCR_TAG_BASE)
    elif len(args) == 3:
        dd, xyz_axis, vec = args
    else:
        raise TypeError("invalid number of arguments")

    return _apply_stiffness_transpose_operator(
        dcoll, dof_desc.DD_VOLUME, dd, vec, xyz_axis
    )


def weak_local_div(dcoll, *args):
    r"""Return the element-local weak divergence of the vector volume function
    represented by *vecs*.

    May be called with ``(vecs)`` or ``(dd, vecs)``.

    :arg dd: a :class:`~grudge.dof_desc.DOFDesc`, or a value convertible to one.
        Defaults to the base volume discretization if not provided.
    :arg vec: a object array of
        a :class:`~meshmode.dof_array.DOFArray`\ s,
        where the last axis of the array must have length
        matching the volume dimension.
    :returns: a :class:`~meshmode.dof_array.DOFArray`
    """
    if len(args) == 1:
        vecs, = args
        dd = dof_desc.DOFDesc("vol", dof_desc.DISCR_TAG_BASE)
    elif len(args) == 2:
        dd, vecs = args
    else:
        raise TypeError("invalid number of arguments")

    return _div_helper(
        dcoll,
        lambda i, subvec: weak_local_d_dx(dcoll, dd, i, subvec),
        vecs
    )

# }}}


# {{{ Mass operator

def reference_mass_matrix(actx, out_element_group, in_element_group):
    @keyed_memoize_in(
        actx, reference_mass_matrix,
        lambda out_grp, in_grp: (out_grp.discretization_key(),
                                 in_grp.discretization_key()))
    def get_ref_mass_mat(out_grp, in_grp):
        if out_grp == in_grp:
            from meshmode.discretization.poly_element import mass_matrix

            return actx.freeze(
                actx.from_numpy(
                    np.asarray(
                        mass_matrix(out_grp),
                        order="C"
                    )
                )
            )

        from modepy import vandermonde
        basis = out_grp.basis_obj()
        vand = vandermonde(basis.functions, out_grp.unit_nodes)
        o_vand = vandermonde(basis.functions, in_grp.unit_nodes)
        vand_inv_t = np.linalg.inv(vand).T

        weights = in_grp.quadrature_rule().weights
        return actx.freeze(
            actx.from_numpy(
                np.asarray(
                    np.einsum("j,ik,jk->ij", weights, vand_inv_t, o_vand),
                    order="C"
                )
            )
        )

    return get_ref_mass_mat(out_element_group, in_element_group)


def _apply_mass_operator(dcoll, dd_out, dd_in, vec):
    from grudge.geometry import area_element

    in_discr = dcoll.discr_from_dd(dd_in)
    out_discr = dcoll.discr_from_dd(dd_out)

    actx = vec.array_context
    area_elements = area_element(actx, dcoll, dd=dd_in)
    return DOFArray(
        actx,
        tuple(
            actx.einsum("ij,ej,ej->ei",
                        reference_mass_matrix(
                            actx,
                            out_element_group=out_grp,
                            in_element_group=in_grp
                        ),
                        ae_i,
                        vec_i,
                        arg_names=("mass_mat", "jac_det", "vec"),
                        tagged=(MassOperatorTag(),))

            for in_grp, out_grp, ae_i, vec_i in zip(
                    in_discr.groups, out_discr.groups, area_elements, vec)
        )
    )


def mass(dcoll, *args):
    if len(args) == 1:
        vec, = args
        dd = dof_desc.DOFDesc("vol", dof_desc.QTAG_NONE)
    elif len(args) == 2:
        dd, vec = args
    else:
        raise TypeError("invalid number of arguments")

    if isinstance(vec, np.ndarray):
        return obj_array_vectorize(
            lambda el: mass(dcoll, dd, el), vec
        )

    return _apply_mass_operator(dcoll, dof_desc.DD_VOLUME, dd, vec)

# }}}


# {{{ Mass inverse operator

def reference_inverse_mass_matrix(actx, element_group):
    @keyed_memoize_in(
        actx, reference_inverse_mass_matrix,
        lambda grp: grp.discretization_key())
    def get_ref_inv_mass_mat(grp):
        from modepy import inverse_mass_matrix
        basis = grp.basis_obj()

        return actx.freeze(
            actx.from_numpy(
                np.asarray(
                    inverse_mass_matrix(basis.functions, grp.unit_nodes),
                    order="C"
                )
            )
        )

    return get_ref_inv_mass_mat(element_group)


def _apply_inverse_mass_operator(dcoll, dd_out, dd_in, vec):
    from grudge.geometry import area_element

    if dd_out != dd_in:
        raise ValueError(
            "Cannot compute inverse of a mass matrix mapping "
            "between different element groups; inverse is not "
            "guaranteed to be well-defined"
        )
    discr = dcoll.discr_from_dd(dd_in)
    use_wadg = not all(grp.is_affine for grp in discr.groups)

    actx = vec.array_context
    inv_area_elements = 1./area_element(actx, dcoll, dd=dd_in)
    if use_wadg:
        # FIXME: Think of how to compose existing functions here...
        # NOTE: Rewritten for readability/debuggability
        grps = discr.groups
        data = []
        for grp, jac_inv, x in zip(grps, inv_area_elements, vec):
            ref_mass = reference_mass_matrix(actx,
                                             out_element_group=grp,
                                             in_element_group=grp)
            ref_mass_inv = reference_inverse_mass_matrix(actx,
                                                         element_group=grp)
            data.append(
                # Based on https://arxiv.org/pdf/1608.03836.pdf
                # true_Minv ~ ref_Minv * ref_M * (1/jac_det) * ref_Minv
                actx.einsum("ik,km,em,mj,ej->ei",
                            ref_mass_inv, ref_mass, jac_inv, ref_mass_inv, x,
                            tagged=(MassOperatorTag(),))
            )
        return DOFArray(actx, data=tuple(data))
    else:
        return DOFArray(
            actx,
            tuple(
                actx.einsum("ij,ej,ej->ei",
                            reference_inverse_mass_matrix(
                                actx,
                                element_group=grp
                            ),
                            iae_i,
                            vec_i,
                            arg_names=("mass_inv_mat", "jac_det_inv", "vec"),
                            tagged=(MassOperatorTag(),))

                for grp, iae_i, vec_i in zip(discr.groups,
                                             inv_area_elements, vec)
            )
        )


def inverse_mass(dcoll, vec):
    if isinstance(vec, np.ndarray):
        return obj_array_vectorize(
            lambda el: inverse_mass(dcoll, el), vec
        )

    return _apply_inverse_mass_operator(
        dcoll, dof_desc.DD_VOLUME, dof_desc.DD_VOLUME, vec
    )

# }}}


# {{{ Face mass operator

def reference_face_mass_matrix(actx, face_element_group, vol_element_group, dtype):

    @keyed_memoize_in(
        actx, reference_mass_matrix,
        lambda face_grp, vol_grp: (face_grp.discretization_key(),
                                   vol_grp.discretization_key()))
    def get_ref_face_mass_mat(face_grp, vol_grp):
        nfaces = vol_grp.mesh_el_group.nfaces
        assert (face_grp.nelements
                == nfaces * vol_grp.nelements)

        matrix = np.empty(
            (vol_grp.nunit_dofs,
            nfaces,
            face_grp.nunit_dofs),
            dtype=dtype
        )

        import modepy as mp
        from meshmode.discretization import ElementGroupWithBasis
        from meshmode.discretization.poly_element import \
            QuadratureSimplexElementGroup

        n = vol_grp.order
        m = face_grp.order
        vol_basis = vol_grp.basis_obj()
        faces = mp.faces_for_shape(vol_grp.shape)

        for iface, face in enumerate(faces):
            # If the face group is defined on a higher-order
            # quadrature grid, use the underlying quadrature rule
            if isinstance(face_grp, QuadratureSimplexElementGroup):
                face_quadrature = face_grp.quadrature_rule()
                if face_quadrature.exact_to < m:
                    raise ValueError(
                        "The face quadrature rule is only exact for polynomials "
                        f"of total degree {face_quadrature.exact_to}. Please "
                        "ensure a quadrature rule is used that is at least "
                        f"exact for degree {m}."
                    )
            else:
                # NOTE: This handles the general case where
                # volume and surface quadrature rules may have different
                # integration orders
                face_quadrature = mp.quadrature_for_space(
                    mp.space_for_shape(face, 2*max(n, m)),
                    face
                )

            # If the group has a nodal basis and is unisolvent,
            # we use the basis on the face to compute the face mass matrix
            if (isinstance(face_grp, ElementGroupWithBasis)
                    and face_grp.space.space_dim
                    == face_grp.nunit_dofs):

                face_basis = face_grp.basis_obj()

                # Sanity check for face quadrature accuracy. Not integrating
                # degree N + M polynomials here is asking for a bad time.
                if face_quadrature.exact_to < m + n:
                    raise ValueError(
                        "The face quadrature rule is only exact for polynomials "
                        f"of total degree {face_quadrature.exact_to}. Please "
                        "ensure a quadrature rule is used that is at least "
                        f"exact for degree {n+m}."
                    )

                matrix[:, iface, :] = mp.nodal_mass_matrix_for_face(
                    face, face_quadrature,
                    face_basis.functions, vol_basis.functions,
                    vol_grp.unit_nodes,
                    face_grp.unit_nodes,
                )
            else:
                # Otherwise, we use a routine that is purely quadrature-based
                # (no need for explicit face basis functions)
                matrix[:, iface, :] = mp.nodal_quad_mass_matrix_for_face(
                    face,
                    face_quadrature,
                    vol_basis.functions,
                    vol_grp.unit_nodes,
                )

        return actx.freeze(actx.from_numpy(matrix))

    return get_ref_face_mass_mat(face_element_group, vol_element_group)


def _apply_face_mass_operator(dcoll, dd, vec):
    from grudge.geometry import area_element

    volm_discr = dcoll.discr_from_dd(dof_desc.DD_VOLUME)
    face_discr = dcoll.discr_from_dd(dd)
    dtype = vec.entry_dtype
    actx = vec.array_context
    surf_area_elements = area_element(actx, dcoll, dd=dd)

    @memoize_in(actx, (_apply_face_mass_operator, "face_mass_knl"))
    def prg():
        return make_loopy_program(
            """{[iel,idof,f,j]:
                0<=iel<nelements and
                0<=f<nfaces and
                0<=idof<nvol_nodes and
                0<=j<nface_nodes}""",
            """
            result[iel,idof] = sum(f, sum(j, mat[idof, f, j]        \
                                             * jac_surf[f, iel, j]  \
                                             * vec[f, iel, j]))
            """,
            name="face_mass"
        )

    result = volm_discr.empty(actx, dtype=dtype)
    assert len(face_discr.groups) == len(volm_discr.groups)

    for afgrp, volgrp in zip(face_discr.groups, volm_discr.groups):

        nfaces = volgrp.mesh_el_group.nfaces
        matrix = reference_face_mass_matrix(
            actx,
            face_element_group=afgrp,
            vol_element_group=volgrp,
            dtype=dtype
        )
        input_view = vec[afgrp.index].reshape(
            nfaces, volgrp.nelements, afgrp.nunit_dofs
        )
        jac_surf = surf_area_elements[afgrp.index].reshape(
            nfaces, volgrp.nelements, afgrp.nunit_dofs
        )
        actx.call_loopy(
            prg(),
            mat=matrix,
            result=result[volgrp.index],
            jac_surf=jac_surf,
            vec=input_view
        )
    return result


def face_mass(dcoll, *args):
    if len(args) == 1:
        vec, = args
        dd = dof_desc.DOFDesc("all_faces", dof_desc.QTAG_NONE)
    elif len(args) == 2:
        dd, vec = args
    else:
        raise TypeError("invalid number of arguments")

    if isinstance(vec, np.ndarray):
        return obj_array_vectorize(
                lambda el: face_mass(dcoll, dd, el), vec)

    return _apply_face_mass_operator(dcoll, dd, vec)

# }}}


# {{{ Nodal reductions TODO: Convert these over

def norm(dcoll, vec, p, dd=None):
    # Raise a warning if `dd` is not None?
    # actx = vec.array_context
    # return actx.np.linalg.norm(vec, ord=p)
    if dd is None:
        dd = "vol"

    dd = dof_desc.as_dofdesc(dd)

    if isinstance(vec, np.ndarray):
        if p == 2:
            return sum(norm(dcoll, vec[idx], p, dd=dd)**2
                       for idx in np.ndindex(vec.shape))**0.5
        elif p == np.inf:
            return max(norm(dcoll, vec[idx], np.inf, dd=dd)
                       for idx in np.ndindex(vec.shape))
        else:
            raise ValueError("unsupported norm order")

    return _norm(dcoll, p, dd)(arg=vec)
    # actx = vec.array_context
    # return actx.np.linalg.norm(vec, ord=p)


@memoize_on_first_arg
def _norm(dcoll, p, dd):
    return bind(dcoll,
            sym.norm(p, sym.var("arg", dd=dd), dd=dd),
            local_only=True)


def nodal_sum(dcoll, dd, vec):
    # Raise a warning if `dd` is not None?
    # actx = vec.array_context
    # return np.sum([actx.np.sum(vec_i) for vec_i in vec])
    return _nodal_reduction(dcoll, sym.NodalSum, dd)(arg=vec)


def nodal_min(dcoll, dd, vec):
    # Raise a warning if `dd` is not None?
    # actx = vec.array_context
    # return np.min([actx.np.min(vec_i) for vec_i in vec])
    return _nodal_reduction(dcoll, sym.NodalMin, dd)(arg=vec)


def nodal_max(dcoll, dd, vec):
    # Raise a warning if `dd` is not None?
    # actx = vec.array_context
    # return np.max([actx.np.max(vec_i) for vec_i in vec])
    return _nodal_reduction(dcoll, sym.NodalMax, dd)(arg=vec)


@memoize_on_first_arg
def _nodal_reduction(dcoll, operator, dd):
    return bind(dcoll, operator(dd)(sym.var("arg")), local_only=True)

# }}}


@memoize_on_first_arg
def connected_ranks(dcoll):
    from meshmode.distributed import get_connected_partitions
    return get_connected_partitions(dcoll._volume_discr.mesh)


# {{{ interior_trace_pair

def interior_trace_pair(dcoll, vec):
    """Return a :class:`grudge.sym.TracePair` for the interior faces of
    *dcoll*.
    """
    i = project(dcoll, "vol", "int_faces", vec)

    def get_opposite_face(el):
        if isinstance(el, Number):
            return el
        else:
            return dcoll.opposite_face_connection()(el)

    e = obj_array_vectorize(get_opposite_face, i)

    return TracePair("int_faces", interior=i, exterior=e)

# }}}


# {{{ distributed-memory functionality

class _RankBoundaryCommunication:
    base_tag = 1273

    def __init__(self, dcoll, remote_rank, vol_field, tag=None):
        self.tag = self.base_tag
        if tag is not None:
            self.tag += tag

        self.dcoll = dcoll
        self.array_context = vol_field.array_context
        self.remote_btag = BTAG_PARTITION(remote_rank)

        self.bdry_discr = dcoll.discr_from_dd(self.remote_btag)
        self.local_dof_array = project(dcoll, "vol", self.remote_btag, vol_field)

        local_data = self.array_context.to_numpy(flatten(self.local_dof_array))

        comm = self.dcoll.mpi_communicator

        self.send_req = comm.Isend(
                local_data, remote_rank, tag=self.tag)

        self.remote_data_host = np.empty_like(local_data)
        self.recv_req = comm.Irecv(self.remote_data_host, remote_rank, self.tag)

    def finish(self):
        self.recv_req.Wait()

        actx = self.array_context
        remote_dof_array = unflatten(self.array_context, self.bdry_discr,
                actx.from_numpy(self.remote_data_host))

        bdry_conn = self.dcoll.get_distributed_boundary_swap_connection(
                dof_desc.as_dofdesc(dof_desc.DTAG_BOUNDARY(self.remote_btag)))
        swapped_remote_dof_array = bdry_conn(remote_dof_array)

        self.send_req.Wait()

        return TracePair(self.remote_btag,
                interior=self.local_dof_array,
                exterior=swapped_remote_dof_array)


def _cross_rank_trace_pairs_scalar_field(dcoll, vec, tag=None):
    if isinstance(vec, Number):
        return [TracePair(BTAG_PARTITION(remote_rank), interior=vec, exterior=vec)
                for remote_rank in connected_ranks(dcoll)]
    else:
        rbcomms = [_RankBoundaryCommunication(dcoll, remote_rank, vec, tag=tag)
                for remote_rank in connected_ranks(dcoll)]
        return [rbcomm.finish() for rbcomm in rbcomms]


def cross_rank_trace_pairs(dcoll, ary, tag=None):
    r"""Get a list of *ary* trace pairs for each partition boundary.

    For each partition boundary, the field data values in *ary* are
    communicated to/from the neighboring partition. Presumably, this
    communication is MPI (but strictly speaking, may not be, and this
    routine is agnostic to the underlying communication, see e.g.
    _cross_rank_trace_pairs_scalar_field).

    For each face on each partition boundary, a :class:`TracePair` is
    created with the locally, and remotely owned partition boundary face
    data as the `internal`, and `external` components, respectively.
    Each of the TracePair components are structured like *ary*.

    The input field data *ary* may be a single
    :class:`~meshmode.dof_array.DOFArray`, or an object
    array of ``DOFArray``\ s of arbitrary shape.
    """
    from pytools.obj_array import make_obj_array

    if isinstance(ary, np.ndarray):
        oshape = ary.shape
        comm_vec = ary.flatten()

        n, = comm_vec.shape
        result = {}
        # FIXME: Batch this communication rather than
        # doing it in sequence.
        for ivec in range(n):
            for rank_tpair in _cross_rank_trace_pairs_scalar_field(
                    dcoll, comm_vec[ivec]):
                assert isinstance(rank_tpair.dd.domain_tag, dof_desc.DTAG_BOUNDARY)
                assert isinstance(rank_tpair.dd.domain_tag.tag, BTAG_PARTITION)
                result[rank_tpair.dd.domain_tag.tag.part_nr, ivec] = rank_tpair

        return [
            TracePair(
                dd=dof_desc.as_dofdesc(
                    dof_desc.DTAG_BOUNDARY(BTAG_PARTITION(remote_rank))),
                interior=make_obj_array([
                    result[remote_rank, i].int for i in range(n)]).reshape(oshape),
                exterior=make_obj_array([
                    result[remote_rank, i].ext for i in range(n)]).reshape(oshape)
                )
            for remote_rank in connected_ranks(dcoll)]
    else:
        return _cross_rank_trace_pairs_scalar_field(dcoll, ary, tag=tag)

# }}}


# vim: foldmethod=marker
